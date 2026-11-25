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

    Un "turno" es todo lo que pasa entre un mensaje de la analista (o un clic en
    Aprobar / Rechazar) y la respuesta. El `Turno` trae la lista de herramientas
    llamadas, EN ORDEN, con su resultado: así siempre se ve qué pidió el modelo (CA4).

Confirmación humana (CA3, HU-5, RN4 · Paso 13):
    Las herramientas marcadas `requiere_confirmacion` (`proveedor_confirmar_campo` y
    `proveedor_simular_envio`) NO se ejecutan cuando el modelo las pide:

        el modelo pide proveedor_confirmar_campo {caso, etiqueta, decision}
          → el ciclo crea una CONFIRMACIÓN PENDIENTE con esos argumentos (ya validados)
          → el modelo recibe "pendiente de aprobación" y se lo explica a la analista
          → la analista pulsa Aprobar o Rechazar → `Agente.resolver(...)`
              Aprobar  → se ejecuta con los argumentos GUARDADOS (el modelo ya no puede
                         cambiarlos) y con una `Aprobacion` en el contexto
              Rechazar → no se ejecuta nada
          → el modelo recibe un aviso con lo que pasó y continúa

    Solo se aprueba con esa acción explícita, nunca interpretando un texto como "sí".
    Si la analista escribe otro mensaje sin resolver las pendientes, se CANCELAN
    (RN4: la aprobación debe venir en el turno inmediatamente siguiente).
    Además, la capa de herramientas tiene su propio candado (`base.py`): sin una
    `Aprobacion` para esa herramienta y esos argumentos, se niega a ejecutar.

Otras reglas del ciclo (sección 9.3 del plan):
    - CA1 · Topes: un máximo de consultas al modelo por turno y de tokens por sesión.
      Al llegar a uno, el CÓDIGO (no el modelo) responde con lo hecho y lo que falta.
    - CA5 · Errores: un error del modelo no cierra la sesión; uno de una herramienta
      le llega al modelo como resultado con error, para que lo explique.
    - Al modelo solo le llegan los resultados enmascarados (`Resultado.a_json()`).

El historial (`Sesion.mensajes`) guarda lo que dijeron la analista y el modelo, los
resultados de las herramientas y los avisos del sistema sobre las confirmaciones. Los
mensajes de topes y errores se le muestran a la analista, pero no entran al historial.
"""

import dataclasses
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
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
from registro_proveedor.herramientas.base import Aprobacion, Contexto, Registro, Resultado
from registro_proveedor.observabilidad import (
    RegistroLlamada,
    enmascarar_datos,
    escribir_auditoria,
    obtener_logger,
)

# Los avisos del sistema al modelo empiezan así, para que los distinga de lo que
# escribe la analista. Solo informan: ninguna acción depende de ellos.
AVISO = "[Aviso del sistema]"

# Lo que recibe el modelo cuando pide una acción que requiere aprobación.
PENDIENTE = (
    "Todavía NO se hizo. La analista debe aprobarla o rechazarla con los botones "
    "Aprobar / Rechazar. No diga que se hizo: dígale qué se va a hacer y que decida."
)


class FinTurno(StrEnum):
    """Por qué terminó un turno."""

    RESPONDIO = "respondio"  # el modelo respondió con texto: lo normal
    TOPE_ITERACIONES = "tope_iteraciones"  # CA1: demasiadas consultas en un turno
    TOPE_TOKENS = "tope_tokens"  # CA1: la sesión gastó su tope de tokens
    ERROR_MODELO = "error_modelo"  # CA5: el proveedor falló; la sesión sigue
    INCOMPLETA = "incompleta"  # la respuesta se cortó (largo máximo o pausa)
    RECHAZO = "rechazo"  # el modelo se negó a responder
    CONFIRMACION_INVALIDA = "confirmacion_invalida"  # se quiso resolver una que no existe


class EstadoLlamada(StrEnum):
    """Qué pasó con una herramienta que pidió el modelo."""

    EJECUTADA = "ejecutada"  # se ejecutó y salió bien
    FALLO = "fallo"  # se intentó y respondió con error (ok=False)
    PENDIENTE = "pendiente"  # requiere aprobación: quedó esperando a la analista
    APROBADA = "aprobada"  # la analista la aprobó y se ejecutó bien
    RECHAZADA = "rechazada"  # la analista la rechazó: no se ejecutó


SIMBOLOS = {
    EstadoLlamada.EJECUTADA: "✓",
    EstadoLlamada.FALLO: "✗",
    EstadoLlamada.PENDIENTE: "⏳",
    EstadoLlamada.APROBADA: "✓ aprobada ·",
    EstadoLlamada.RECHAZADA: "⊘ rechazada ·",
}


@dataclass(frozen=True)
class LlamadaEjecutada:
    """Una herramienta que pidió el modelo en este turno, y qué pasó con ella."""

    orden: int  # 1, 2, 3… dentro del turno
    nombre: str
    argumentos: dict[str, object]  # enmascarados, por si acaso
    estado: EstadoLlamada
    resumen: str  # la misma frase de log.jsonl ("14 llenos · 1 faltante…") o el error

    @property
    def ok(self) -> bool:
        return self.estado in (EstadoLlamada.EJECUTADA, EstadoLlamada.APROBADA)

    @property
    def simbolo(self) -> str:
        return SIMBOLOS[self.estado]


@dataclass(frozen=True)
class ConfirmacionPendiente:
    """Una acción que pidió el modelo y que espera la aprobación de la analista."""

    id: str
    herramienta: str
    argumentos: dict[str, object]  # ya validados: con estos EXACTOS se ejecutará
    descripcion: str  # para mostrarla: "proveedor_confirmar_campo: caso … · etiqueta …"
    creada_en: datetime


@dataclass(frozen=True)
class Turno:
    """Lo que devuelve el agente después de un mensaje o de resolver una confirmación."""

    texto: str  # lo que se le muestra a la analista
    fin: FinTurno
    llamadas: tuple[LlamadaEjecutada, ...]  # en el orden en que se ejecutaron
    consultas: int  # cuántas veces se consultó al modelo en este turno
    uso: Uso  # tokens gastados en este turno
    # Las confirmaciones que quedaron esperando a la analista (para los botones).
    pendientes: tuple[ConfirmacionPendiente, ...] = ()
    # Las que se cancelaron al empezar este turno porque la analista escribió un mensaje
    # sin resolverlas (RN4). Se devuelven para MOSTRARLO: no basta con que lo sepa el modelo.
    canceladas: tuple[ConfirmacionPendiente, ...] = ()


@dataclass
class Sesion:
    """Una conversación: contexto, historial, tokens gastados y confirmaciones pendientes.

    Vive en memoria. En el Paso 15 la API la guardará entre un mensaje y otro.
    """

    contexto: Contexto
    mensajes: list[Mensaje] = field(default_factory=list)
    uso: Uso = field(default_factory=Uso)
    pendientes: dict[str, ConfirmacionPendiente] = field(default_factory=dict)

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

    # ---------- Las dos entradas: un mensaje, o Aprobar / Rechazar ----------

    def responder(self, sesion: Sesion, mensaje: str) -> Turno:
        """Procesa un mensaje de la analista y devuelve la respuesta. Nunca lanza por el modelo.

        Si había confirmaciones pendientes, se cancelan (RN4) y el modelo se entera.
        """
        canceladas = _cancelar_pendientes(sesion)
        textos = [mensaje]
        if canceladas:
            textos.insert(0, _aviso_de_cancelacion(canceladas))
        _agregar_del_usuario(sesion, textos)
        return self._continuar(sesion, [], canceladas=tuple(canceladas))

    def resolver(self, sesion: Sesion, id_confirmacion: str, *, aprobar: bool) -> Turno:
        """La analista aprobó o rechazó una confirmación pendiente (botón o `/aprobar`).

        Aprobar ejecuta la acción con los argumentos guardados; rechazar no ejecuta nada.
        Después, el modelo recibe un aviso con lo que pasó y continúa la conversación.
        Una confirmación que no existe (o que ya se resolvió) no ejecuta nada.
        """
        pendiente = sesion.pendientes.pop(id_confirmacion, None)
        if pendiente is None:
            return Turno(
                texto=f"No hay ninguna acción pendiente con el identificador «{id_confirmacion}» "
                "(ya se resolvió, se canceló o no existe). No se ejecutó nada.",
                fin=FinTurno.CONFIRMACION_INVALIDA,
                llamadas=(),
                consultas=0,
                uso=Uso(),
                pendientes=tuple(sesion.pendientes.values()),
            )
        if aprobar:
            llamada, aviso = self._ejecutar_aprobada(sesion, pendiente)
        else:
            llamada, aviso = _rechazar(sesion, pendiente)
        _agregar_del_usuario(sesion, [aviso])
        return self._continuar(sesion, [llamada])

    # ---------- El ciclo ----------

    def _continuar(
        self,
        sesion: Sesion,
        llamadas: list[LlamadaEjecutada],
        canceladas: tuple[ConfirmacionPendiente, ...] = (),
    ) -> Turno:
        """Consulta al modelo y ejecuta lo que pide, hasta que responda con texto o haya un tope."""
        uso = Uso()

        def turno(texto: str, fin: FinTurno, consultas: int) -> Turno:
            return Turno(
                texto=texto,
                fin=fin,
                llamadas=tuple(llamadas),
                consultas=consultas,
                uso=uso,
                pendientes=tuple(sesion.pendientes.values()),
                canceladas=canceladas,
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
                resultados = [self._atender(sesion, ll, llamadas) for ll in respuesta.llamadas]
                sesion.mensajes.append(Mensaje.con_resultados(resultados))
                continue

            texto, fin = _cerrar(sesion, respuesta)
            return turno(texto, fin, consulta)

        return turno(
            _texto_tope_iteraciones(self._max_iteraciones, llamadas),
            FinTurno.TOPE_ITERACIONES,
            self._max_iteraciones,
        )

    # ---------- Atender lo que pide el modelo ----------

    def _atender(
        self, sesion: Sesion, llamada: LlamadaHerramienta, llamadas: list[LlamadaEjecutada]
    ) -> ResultadoHerramienta:
        """Ejecuta lo que pidió el modelo (o lo deja pendiente), lo anota y prepara su resultado."""
        herramienta = self._registro.obtener(llamada.nombre)
        resultado: Resultado[object]
        if herramienta is not None and herramienta.requiere_confirmacion:
            resultado = self._dejar_pendiente(sesion, llamada)
            estado = EstadoLlamada.PENDIENTE if resultado.ok else EstadoLlamada.FALLO
            resumen = (
                f"pendiente de aprobación (confirmación {_id_de(resultado)})"
                if resultado.ok
                else self._registro.resumir(llamada.nombre, resultado)
            )
        else:
            # Valida los argumentos, ejecuta y deja la línea en log.jsonl. Nunca lanza:
            # una herramienta inexistente o un argumento inventado vuelven como ok=False.
            resultado = self._registro.ejecutar(llamada.nombre, llamada.argumentos, sesion.contexto)
            estado = EstadoLlamada.EJECUTADA if resultado.ok else EstadoLlamada.FALLO
            resumen = self._registro.resumir(llamada.nombre, resultado)
        llamadas.append(
            LlamadaEjecutada(
                orden=len(llamadas) + 1,
                nombre=llamada.nombre,
                argumentos=_enmascarados(llamada.argumentos),
                estado=estado,
                resumen=resumen,
            )
        )
        return ResultadoHerramienta(
            id_llamada=llamada.id,
            contenido=resultado.a_json(),  # enmascarado: al modelo, solo lo mínimo
            es_error=not resultado.ok,
        )

    def _dejar_pendiente(self, sesion: Sesion, llamada: LlamadaHerramienta) -> Resultado[object]:
        """Crea la confirmación pendiente (sin ejecutar nada) y responde "pendiente" al modelo.

        Los argumentos se validan ANTES: no tiene sentido pedir que se apruebe algo que
        de todas formas fallaría. Si el modelo pide dos veces lo mismo, se reutiliza la
        confirmación que ya existe.
        """
        validados = self._registro.validar_argumentos(llamada.nombre, llamada.argumentos)
        if not validados.ok or validados.data is None:
            return Resultado(ok=False, error=validados.error or "argumentos no válidos")
        argumentos: dict[str, object] = dict(validados.data)
        pendiente = next(
            (
                p
                for p in sesion.pendientes.values()
                if p.herramienta == llamada.nombre and p.argumentos == argumentos
            ),
            None,
        )
        if pendiente is None:
            ctx = sesion.contexto
            pendiente = ConfirmacionPendiente(
                id=uuid.uuid4().hex[:8],
                herramienta=llamada.nombre,
                argumentos=argumentos,
                descripcion=_describir(llamada.nombre, argumentos),
                creada_en=ctx.reloj(),
            )
            sesion.pendientes[pendiente.id] = pendiente
            _auditar(
                ctx,
                pendiente,
                f"no ejecutada: pendiente de aprobación (confirmación {pendiente.id})",
            )
        return Resultado(
            ok=True,
            data={
                "estado": "pendiente_de_aprobacion",
                "confirmacion": pendiente.id,
                "accion": pendiente.descripcion,
                "mensaje": PENDIENTE,
            },
        )

    def _ejecutar_aprobada(
        self, sesion: Sesion, pendiente: ConfirmacionPendiente
    ) -> tuple[LlamadaEjecutada, str]:
        """Ejecuta la acción aprobada con sus argumentos guardados y una `Aprobacion`."""
        ctx = sesion.contexto
        aprobacion = Aprobacion(
            id=pendiente.id,
            herramienta=pendiente.herramienta,
            argumentos=pendiente.argumentos,
            por=ctx.usuario,
            en=ctx.reloj(),
        )
        # `replace` crea una COPIA del contexto con la aprobación: el de la sesión sigue
        # sin ella, así que no sirve para ninguna otra acción.
        resultado = self._registro.ejecutar(
            pendiente.herramienta,
            pendiente.argumentos,
            dataclasses.replace(ctx, aprobacion=aprobacion),
        )
        llamada = LlamadaEjecutada(
            orden=1,
            nombre=pendiente.herramienta,
            argumentos=_enmascarados(pendiente.argumentos),
            estado=EstadoLlamada.APROBADA if resultado.ok else EstadoLlamada.FALLO,
            resumen=self._registro.resumir(pendiente.herramienta, resultado),
        )
        aviso = (
            f"{AVISO} La analista APROBÓ la acción pendiente {pendiente.id} "
            f"({pendiente.descripcion}). Resultado de ejecutarla: {resultado.a_json()}"
        )
        return llamada, aviso

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


# ---------- Confirmaciones: piezas sueltas ----------


def _cancelar_pendientes(sesion: Sesion) -> list[ConfirmacionPendiente]:
    """RN4: un mensaje nuevo sin aprobar cancela las pendientes. Devuelve las canceladas."""
    canceladas = list(sesion.pendientes.values())
    sesion.pendientes.clear()
    for p in canceladas:
        _auditar(sesion.contexto, p, f"cancelada sin ejecutar (confirmación {p.id})")
    return canceladas


def _aviso_de_cancelacion(canceladas: list[ConfirmacionPendiente]) -> str:
    """Lo que recibe el modelo antes del mensaje de la analista, para que sepa qué se canceló."""
    lista = "; ".join(f"{p.id} ({p.descripcion})" for p in canceladas)
    return (
        f"{AVISO} Se cancelaron sin ejecutar las acciones pendientes de aprobación: "
        f"{lista}. La analista escribió un mensaje sin aprobarlas."
    )


def _rechazar(sesion: Sesion, pendiente: ConfirmacionPendiente) -> tuple[LlamadaEjecutada, str]:
    _auditar(sesion.contexto, pendiente, f"rechazada por la analista (confirmación {pendiente.id})")
    llamada = LlamadaEjecutada(
        orden=1,
        nombre=pendiente.herramienta,
        argumentos=_enmascarados(pendiente.argumentos),
        estado=EstadoLlamada.RECHAZADA,
        resumen="la analista la rechazó: no se ejecutó",
    )
    aviso = (
        f"{AVISO} La analista RECHAZÓ la acción pendiente {pendiente.id} "
        f"({pendiente.descripcion}). No se ejecutó nada."
    )
    return llamada, aviso


def _describir(herramienta: str, argumentos: dict[str, object]) -> str:
    """ "proveedor_confirmar_campo: caso ec-corp-andina · etiqueta RUC · decision aceptar"."""
    partes = " · ".join(f"{k} {v}" for k, v in _enmascarados(argumentos).items())
    return f"{herramienta}: {partes}" if partes else herramienta


def _id_de(resultado: Resultado[object]) -> str:
    data = resultado.data
    return str(data.get("confirmacion", "?")) if isinstance(data, dict) else "?"


def _enmascarados(argumentos: dict[str, object]) -> dict[str, object]:
    enmascarados = enmascarar_datos(argumentos)
    return enmascarados if isinstance(enmascarados, dict) else {}


def _auditar(ctx: Contexto, pendiente: ConfirmacionPendiente, resumen: str) -> None:
    """Deja en log.jsonl qué pasó con una acción que requiere aprobación (sin ejecutarla)."""
    caso = pendiente.argumentos.get("caso")
    escribir_auditoria(
        ctx.salida,
        RegistroLlamada(
            ts=ctx.reloj(),
            sesion=ctx.sesion_id,
            herramienta=pendiente.herramienta,
            caso=caso if isinstance(caso, str) and re.fullmatch(PATRON_ID_CASO, caso) else None,
            ok=False,
            resumen=resumen,
            duracion_ms=0,
            aprobacion=pendiente.id,
        ),
    )


# ---------- El historial ----------


def _agregar_del_usuario(sesion: Sesion, textos: list[str]) -> None:
    """Agrega al historial lo que va del lado del usuario: el mensaje y los avisos del sistema.

    Si el último mensaje ya es del usuario (porque el turno anterior terminó en un tope
    o en un error, justo después de los resultados de las herramientas), los textos se
    agregan A ESE mensaje: la conversación debe alternar usuario / asistente (D45).
    """
    nuevos = [BloqueTexto(texto=t) for t in textos]
    if sesion.mensajes and sesion.mensajes[-1].rol is Rol.USUARIO:
        ultimo = sesion.mensajes[-1]
        sesion.mensajes[-1] = Mensaje(rol=Rol.USUARIO, bloques=[*ultimo.bloques, *nuevos])
    else:
        sesion.mensajes.append(Mensaje(rol=Rol.USUARIO, bloques=list(nuevos)))


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


# ---------- Mensajes que arma el código (no el modelo) ----------


def _lo_que_se_hizo(llamadas: list[LlamadaEjecutada]) -> str:
    if not llamadas:
        return "No alcancé a ejecutar ninguna herramienta."
    lineas = ["Esto es lo que alcancé a hacer:"]
    lineas += [f"{ll.orden}. {ll.simbolo} {ll.nombre}: {ll.resumen}" for ll in llamadas]
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
