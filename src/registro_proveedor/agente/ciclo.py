"""El ciclo del agente: mensaje de la analista → modelo → herramientas → modelo → respuesta.

¿Qué hace?
    El modelo de lenguaje NO ejecuta nada: solo PIDE herramientas. Este ciclo es el que
    las ejecuta y le devuelve los resultados, una y otra vez, hasta que el modelo
    responde con texto. Por ejemplo, ante "prepara el caso de Colombia":

        consulta 1 → el modelo pide proveedor_listar_casos       → se ejecuta
        consulta 2 → pide proveedor_leer_solicitud               → se ejecuta
        consulta 3 → pide proveedor_mapear_campos                → se ejecuta
        consulta 4 → pide proveedor_generar_formulario           → se ejecuta
        consulta 5 → pide proveedor_armar_paquete                → se ejecuta
        consulta 6 → responde con el resumen                     → fin del turno

    Un "turno" es todo lo que pasa entre un mensaje de la analista y la respuesta.
    El `Turno` que devuelve `responder` trae la lista de herramientas llamadas, EN
    ORDEN, con su resultado: así siempre se ve qué pidió el modelo (CA4).

Reglas del ciclo (sección 9.3 del plan):
    - CA1 · Topes: un máximo de consultas al modelo por turno y de tokens por sesión.
      Al llegar a uno, el agente responde con lo que alcanzó a hacer y lo que falta.
      Ese mensaje lo arma el CÓDIGO, no el modelo: no gasta otra consulta y no puede
      inventar nada.
    - CA5 · Errores: un error del modelo (sin conexión, clave mala) no cierra la
      sesión: se explica y la conversación sigue. Un error de una herramienta le
      llega al modelo como resultado con error, para que lo explique.
    - CA3 · Confirmación: una herramienta marcada `requiere_confirmacion` NO se
      ejecuta. En este paso se le responde al modelo que necesita aprobación; en el
      Paso 13 se convierte en una confirmación pendiente con Aprobar / Rechazar.
    - Al modelo solo le llegan los resultados enmascarados (`Resultado.a_json()`).

El historial (`Sesion.mensajes`) solo guarda lo que dijeron la analista y el modelo,
más los resultados de las herramientas. Los mensajes del código (topes, errores) se
le muestran a la analista, pero no entran al historial: el modelo no los escribió.
"""

import re
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from registro_proveedor.agente.instrucciones import InstruccionesSistema
from registro_proveedor.agente.llm.adaptador import (
    AdaptadorLLM,
    BloqueTexto,
    ErrorDelModelo,
    LlamadaHerramienta,
    Mensaje,
    MotivoFin,
    RespuestaModelo,
    ResultadoHerramienta,
    Rol,
    Uso,
    definiciones_desde_registro,
)
from registro_proveedor.config import Configuracion
from registro_proveedor.dominio.modelos import PATRON_ID_CASO
from registro_proveedor.herramientas.base import Contexto, Registro, Resultado
from registro_proveedor.observabilidad import (
    RegistroLlamada,
    enmascarar_datos,
    escribir_auditoria,
    obtener_logger,
)

# Lo que recibe el modelo cuando pide una herramienta que requiere aprobación (CA3).
# En el Paso 13 esto se reemplaza por una confirmación pendiente de verdad.
SIN_APROBACION = (
    "en esta versión no se pueden confirmar campos desde el chat. No se hizo ningún "
    "cambio: el campo sigue por confirmar y el paquete no queda listo para firma "
    "mientras siga así."
)


class FinTurno(StrEnum):
    """Por qué terminó un turno."""

    RESPONDIO = "respondio"  # el modelo respondió con texto: lo normal
    TOPE_ITERACIONES = "tope_iteraciones"  # CA1: demasiadas consultas en un turno
    TOPE_TOKENS = "tope_tokens"  # CA1: la sesión gastó su tope de tokens
    ERROR_MODELO = "error_modelo"  # CA5: el proveedor falló; la sesión sigue
    INCOMPLETA = "incompleta"  # la respuesta se cortó (largo máximo o pausa)
    RECHAZO = "rechazo"  # el modelo se negó a responder


@dataclass(frozen=True)
class LlamadaEjecutada:
    """Una herramienta que pidió el modelo en este turno, y cómo le fue."""

    orden: int  # 1, 2, 3… dentro del turno
    nombre: str
    argumentos: dict[str, object]  # enmascarados, por si acaso
    ok: bool
    resumen: str  # la misma frase de log.jsonl ("14 llenos · 1 faltante…") o el error


@dataclass(frozen=True)
class Turno:
    """Lo que devuelve el agente después de un mensaje de la analista."""

    texto: str  # lo que se le muestra a la analista
    fin: FinTurno
    llamadas: tuple[LlamadaEjecutada, ...]  # en el orden en que se ejecutaron
    consultas: int  # cuántas veces se consultó al modelo en este turno
    uso: Uso  # tokens gastados en este turno


@dataclass
class Sesion:
    """Una conversación: su contexto, su historial y los tokens que lleva gastados.

    Vive en memoria. En el Paso 15 la API la guardará entre un mensaje y otro.
    """

    contexto: Contexto
    mensajes: list[Mensaje] = field(default_factory=list)
    uso: Uso = field(default_factory=Uso)

    @property
    def id(self) -> str:
        return self.contexto.sesion_id

    @classmethod
    def nueva(cls, config: Configuracion) -> "Sesion":
        """Una sesión con identificador propio, para que su log no se mezcle con otras."""
        return cls(Contexto.desde_configuracion(config, sesion_id=uuid.uuid4().hex[:12]))


class Agente:
    """El ciclo del agente. No guarda estado de las conversaciones: eso va en `Sesion`."""

    def __init__(
        self,
        *,
        adaptador: AdaptadorLLM,
        registro: Registro,
        instrucciones: InstruccionesSistema,
        max_iteraciones: int = 15,
        tope_tokens_sesion: int = 300_000,
    ) -> None:
        self._adaptador = adaptador
        self._registro = registro
        self._instrucciones = instrucciones
        self._herramientas = definiciones_desde_registro(registro)
        self._max_iteraciones = max_iteraciones
        self._tope_tokens = tope_tokens_sesion

    @classmethod
    def desde_configuracion(
        cls,
        config: Configuracion,
        *,
        adaptador: AdaptadorLLM,
        registro: Registro,
        instrucciones: InstruccionesSistema,
    ) -> "Agente":
        """El agente con los topes de `.env` (LLM_MAX_ITERACIONES, LLM_TOPE_TOKENS_SESION)."""
        return cls(
            adaptador=adaptador,
            registro=registro,
            instrucciones=instrucciones,
            max_iteraciones=config.llm_max_iteraciones,
            tope_tokens_sesion=config.llm_tope_tokens_sesion,
        )

    def responder(self, sesion: Sesion, mensaje: str) -> Turno:
        """Procesa un mensaje de la analista y devuelve la respuesta. Nunca lanza por el modelo."""
        _agregar_del_usuario(sesion, mensaje)
        llamadas: list[LlamadaEjecutada] = []
        uso = Uso()

        def turno(texto: str, fin: FinTurno, consultas: int) -> Turno:
            return Turno(
                texto=texto, fin=fin, llamadas=tuple(llamadas), consultas=consultas, uso=uso
            )

        for consulta in range(1, self._max_iteraciones + 1):
            # El tope de tokens se revisa ANTES de cada consulta. La última puede pasarlo
            # un poco (no se sabe cuánto gastará hasta que responde), pero no hay otra.
            # No cuenta lo leído de la caché, que es casi gratis (D46).
            if sesion.uso.para_tope >= self._tope_tokens:
                return turno(
                    _texto_tope_tokens(self._tope_tokens, llamadas),
                    FinTurno.TOPE_TOKENS,
                    consulta - 1,
                )
            try:
                respuesta = self._adaptador.enviar(
                    self._instrucciones.texto, sesion.mensajes, self._herramientas
                )
            except ErrorDelModelo as e:
                self._registrar_error(sesion, consulta, e)
                return turno(_texto_error(e, llamadas), FinTurno.ERROR_MODELO, consulta)
            uso = uso.sumar(respuesta.uso)
            sesion.uso = sesion.uso.sumar(respuesta.uso)
            self._registrar_consulta(sesion, consulta, respuesta)

            if respuesta.motivo is MotivoFin.PIDE_HERRAMIENTA and respuesta.llamadas:
                # El pedido y sus resultados entran JUNTOS al historial: Anthropic exige
                # que cada pedido de herramienta tenga su resultado en el mensaje siguiente.
                sesion.mensajes.append(respuesta.como_mensaje())
                resultados = [self._ejecutar(sesion, ll, llamadas) for ll in respuesta.llamadas]
                sesion.mensajes.append(Mensaje.con_resultados(resultados))
                continue

            texto, fin = _cerrar(sesion, respuesta)
            return turno(texto, fin, consulta)

        return turno(
            _texto_tope_iteraciones(self._max_iteraciones, llamadas),
            FinTurno.TOPE_ITERACIONES,
            self._max_iteraciones,
        )

    # ---------- Ejecutar una herramienta ----------

    def _ejecutar(
        self, sesion: Sesion, llamada: LlamadaHerramienta, llamadas: list[LlamadaEjecutada]
    ) -> ResultadoHerramienta:
        """Ejecuta lo que pidió el modelo, lo anota en `llamadas` y prepara su resultado."""
        herramienta = self._registro.obtener(llamada.nombre)
        resultado: Resultado[object]
        if herramienta is not None and herramienta.requiere_confirmacion:
            resultado = Resultado(ok=False, error=SIN_APROBACION)
            _auditar_sin_aprobacion(sesion.contexto, llamada)
        else:
            # Valida los argumentos, ejecuta y deja la línea en log.jsonl. Nunca lanza:
            # una herramienta inexistente o un argumento inventado vuelven como ok=False.
            resultado = self._registro.ejecutar(llamada.nombre, llamada.argumentos, sesion.contexto)
        argumentos = enmascarar_datos(llamada.argumentos)
        llamadas.append(
            LlamadaEjecutada(
                orden=len(llamadas) + 1,
                nombre=llamada.nombre,
                argumentos=argumentos if isinstance(argumentos, dict) else {},
                ok=resultado.ok,
                resumen=self._registro.resumir(llamada.nombre, resultado),
            )
        )
        return ResultadoHerramienta(
            id_llamada=llamada.id,
            contenido=resultado.a_json(),  # enmascarado: al modelo, solo lo mínimo
            es_error=not resultado.ok,
        )

    # ---------- Log de operación (HU-7) ----------

    def _registrar_consulta(
        self, sesion: Sesion, consulta: int, respuesta: RespuestaModelo
    ) -> None:
        """Una línea por consulta al modelo: con qué instrucciones, qué pidió y cuánto gastó."""
        obtener_logger().info(
            "consulta_modelo",
            sesion=sesion.id,
            consulta=consulta,
            modelo=respuesta.modelo,
            instrucciones_version=self._instrucciones.version,
            instrucciones_huella=self._instrucciones.huella,
            motivo=str(respuesta.motivo),
            herramientas_pedidas=[ll.nombre for ll in respuesta.llamadas],
            tokens_entrada=respuesta.uso.entrada,
            tokens_salida=respuesta.uso.salida,
            tokens_cache_lectura=respuesta.uso.cache_lectura,
            tokens_cache_escritura=respuesta.uso.cache_escritura,
            tokens_sesion=sesion.uso.total,
            tokens_sesion_para_tope=sesion.uso.para_tope,
            id_solicitud=respuesta.id_solicitud,
        )

    def _registrar_error(self, sesion: Sesion, consulta: int, error: ErrorDelModelo) -> None:
        obtener_logger().warning(
            "error_del_modelo",
            sesion=sesion.id,
            consulta=consulta,
            modelo=self._adaptador.modelo,
            codigo=error.codigo,
            reintentable=error.reintentable,
        )


# ---------- El historial ----------


def _agregar_del_usuario(sesion: Sesion, texto: str) -> None:
    """Agrega el mensaje de la analista al historial.

    Si el último mensaje ya es del usuario (porque el turno anterior terminó en un tope
    o en un error, justo después de los resultados de las herramientas), el texto se
    agrega A ESE mensaje: la conversación debe alternar usuario / asistente.
    """
    nuevo = BloqueTexto(texto=texto)
    if sesion.mensajes and sesion.mensajes[-1].rol is Rol.USUARIO:
        ultimo = sesion.mensajes[-1]
        sesion.mensajes[-1] = Mensaje(rol=Rol.USUARIO, bloques=[*ultimo.bloques, nuevo])
    else:
        sesion.mensajes.append(Mensaje(rol=Rol.USUARIO, bloques=[nuevo]))


def _cerrar(sesion: Sesion, respuesta: RespuestaModelo) -> tuple[str, FinTurno]:
    """El turno termina con esta respuesta: qué mostrar y por qué terminó.

    La respuesta entra al historial solo si tiene texto y no trae pedidos de
    herramienta: un pedido sin su resultado haría fallar la consulta siguiente, y
    Anthropic rechaza un mensaje del asistente vacío.
    """
    texto = respuesta.texto.strip()
    if texto and not respuesta.llamadas:
        sesion.mensajes.append(respuesta.como_mensaje())
    if respuesta.motivo is MotivoFin.RECHAZO:
        return (
            "El modelo no quiso responder a esta solicitud. Puede reformularla.",
            FinTurno.RECHAZO,
        )
    if respuesta.motivo in (MotivoFin.LIMITE_TOKENS, MotivoFin.PAUSA):
        aviso = "(La respuesta quedó incompleta. Escriba «sigue» para que continúe.)"
        return (f"{texto}\n\n{aviso}" if texto else aviso), FinTurno.INCOMPLETA
    return texto or "(El modelo terminó sin escribir una respuesta.)", FinTurno.RESPONDIO


def _auditar_sin_aprobacion(ctx: Contexto, llamada: LlamadaHerramienta) -> None:
    """Deja en log.jsonl que el modelo pidió una acción que requiere aprobación (no se hizo)."""
    caso = llamada.argumentos.get("caso")
    escribir_auditoria(
        ctx.salida,
        RegistroLlamada(
            ts=ctx.reloj(),
            sesion=ctx.sesion_id,
            herramienta=llamada.nombre,
            caso=caso if isinstance(caso, str) and re.fullmatch(PATRON_ID_CASO, caso) else None,
            ok=False,
            resumen="no ejecutada: requiere aprobación de la analista",
            duracion_ms=0,
        ),
    )


# ---------- Mensajes que arma el código (no el modelo) ----------


def _lo_que_se_hizo(llamadas: list[LlamadaEjecutada]) -> str:
    if not llamadas:
        return "No alcancé a ejecutar ninguna herramienta."
    lineas = ["Esto es lo que alcancé a hacer:"]
    lineas += [f"{ll.orden}. {'✓' if ll.ok else '✗'} {ll.nombre}: {ll.resumen}" for ll in llamadas]
    return "\n".join(lineas)


def _miles(numero: int) -> str:
    """300000 → "300 000" (separador de miles con espacio)."""
    return f"{numero:,}".replace(",", " ")


def _texto_tope_iteraciones(tope: int, llamadas: list[LlamadaEjecutada]) -> str:
    return (
        f"Me detuve porque llegué al tope de {tope} consultas al modelo en este mensaje.\n\n"
        f"{_lo_que_se_hizo(llamadas)}\n\n"
        "Lo que falta: revisar esos resultados y seguir con el flujo. "
        "Escriba «sigue» para continuar."
    )


def _texto_tope_tokens(tope: int, llamadas: list[LlamadaEjecutada]) -> str:
    return (
        f"Esta conversación llegó a su tope de {_miles(tope)} tokens y no puedo seguir "
        "consultando al modelo.\n\n"
        f"{_lo_que_se_hizo(llamadas)}\n\n"
        "Los archivos ya generados siguen en out/. Para continuar, inicie una conversación nueva."
    )


def _texto_error(error: ErrorDelModelo, llamadas: list[LlamadaEjecutada]) -> str:
    texto = f"No pude comunicarme con el modelo: {error.mensaje}."
    if error.reintentable:
        texto += " Intente de nuevo en un momento."
    texto += " La conversación sigue abierta."
    if llamadas:
        texto += f"\n\n{_lo_que_se_hizo(llamadas)}"
    return texto
