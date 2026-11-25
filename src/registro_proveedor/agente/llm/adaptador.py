"""El contrato con el modelo de lenguaje: nuestros tipos y el `Protocol` `AdaptadorLLM`.

¿Por qué tipos propios y no los del SDK de Anthropic?
    Decisión D3: cambiar de proveedor no debe tocar el ciclo del agente. Si el ciclo
    usara los tipos de Anthropic, cambiar de proveedor obligaría a reescribirlo. Con
    tipos propios, solo cambia el adaptador. Cada adaptador traduce entre estos tipos y
    los de su proveedor.

Cómo se ve una conversación con herramientas, en estos tipos:

    Mensaje(USUARIO,   [BloqueTexto("procesa el de Ecuador")])
    Mensaje(ASISTENTE, [LlamadaHerramienta(id="t1", nombre="proveedor_listar_casos",
                                           argumentos={"filtro": "Ecuador"})])
    Mensaje(USUARIO,   [ResultadoHerramienta(id_llamada="t1", contenido='{"ok": true, ...}')])
    Mensaje(ASISTENTE, [LlamadaHerramienta(id="t2", nombre="proveedor_leer_solicitud", ...)])
    ...
    Mensaje(ASISTENTE, [BloqueTexto("Listo. El caso de Ecuador tiene 13 campos llenos...")])

El modelo NUNCA ejecuta una herramienta: solo la PIDE (`LlamadaHerramienta`). Quien la
ejecuta es nuestro ciclo (Paso 12), con `registro.ejecutar(...)` y todas sus
protecciones, y le devuelve el resultado (`ResultadoHerramienta`).
"""

from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from registro_proveedor.herramientas.base import Registro


class _Modelo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------- Bloques de un mensaje ----------


class BloqueTexto(_Modelo):
    """Texto: lo que escribe la analista o lo que responde el modelo."""

    tipo: Literal["texto"] = "texto"
    texto: str


class LlamadaHerramienta(_Modelo):
    """El modelo PIDE ejecutar una herramienta. Nuestro código decide si la ejecuta.

    `id` lo pone el proveedor; el resultado debe llevar el mismo id para que el modelo
    sepa a qué pedido responde.
    """

    tipo: Literal["llamada"] = "llamada"
    id: str
    nombre: str
    # `Any`: los argumentos llegan como JSON y varían según la herramienta. Se validan
    # recién al ejecutar, con el modelo de argumentos de cada una (Registro.ejecutar).
    argumentos: dict[str, Any]


class ResultadoHerramienta(_Modelo):
    """Lo que respondió una herramienta, de vuelta para el modelo (texto JSON enmascarado)."""

    tipo: Literal["resultado"] = "resultado"
    id_llamada: str
    contenido: str  # Resultado.a_json(): los datos sensibles ya van como ****2345
    es_error: bool = False  # True si la herramienta respondió ok=False


# Un bloque es uno de los tres. `discriminator="tipo"` le dice a Pydantic cómo
# distinguirlos al leer un JSON (por el campo `tipo`).
Bloque = Annotated[
    BloqueTexto | LlamadaHerramienta | ResultadoHerramienta, Field(discriminator="tipo")
]


class Rol(StrEnum):
    USUARIO = "usuario"  # la analista, o los resultados de herramientas que le devolvemos
    ASISTENTE = "asistente"  # el modelo


class Mensaje(_Modelo):
    """Un turno de la conversación."""

    rol: Rol
    bloques: list[Bloque]
    # Contenido ORIGINAL del proveedor, solo en los mensajes del asistente. Algunos
    # proveedores (Anthropic) exigen que se les devuelva tal cual, con bloques que no
    # tienen equivalente aquí (por ejemplo, el "pensamiento" del modelo). Solo el
    # adaptador que lo produjo sabe leerlo; el resto del código no lo toca.
    # `Any`: su forma depende del proveedor.
    crudo: list[dict[str, Any]] | None = None

    @classmethod
    def del_usuario(cls, texto: str) -> "Mensaje":
        return cls(rol=Rol.USUARIO, bloques=[BloqueTexto(texto=texto)])

    @classmethod
    def con_resultados(cls, resultados: Sequence[ResultadoHerramienta]) -> "Mensaje":
        """Los resultados de las herramientas, TODOS juntos en un solo mensaje del usuario."""
        return cls(rol=Rol.USUARIO, bloques=list(resultados))


# ---------- La respuesta del modelo ----------


class MotivoFin(StrEnum):
    """Por qué el modelo dejó de escribir."""

    TERMINO = "termino"  # terminó su respuesta
    PIDE_HERRAMIENTA = "pide_herramienta"  # quiere que ejecutemos una o más herramientas
    LIMITE_TOKENS = "limite_tokens"  # se quedó sin espacio (LLM_MAX_TOKENS): respuesta cortada
    PAUSA = "pausa"  # el proveedor pausó el turno y se puede continuar
    RECHAZO = "rechazo"  # el proveedor se negó a responder por seguridad


class Uso(_Modelo):
    """Tokens usados en una llamada (para medir el costo en el Paso 18)."""

    entrada: int = 0
    salida: int = 0
    cache_lectura: int = 0  # leídos de la caché: mucho más baratos
    cache_escritura: int = 0  # guardados en la caché esta vez

    @property
    def total(self) -> int:
        """Todos los tokens procesados, de los cuatro tipos (lo que mide el tope por sesión)."""
        return self.entrada + self.salida + self.cache_lectura + self.cache_escritura

    def sumar(self, otro: "Uso") -> "Uso":
        """Un uso nuevo con los tokens de los dos (para acumular por turno y por sesión)."""
        return Uso(
            entrada=self.entrada + otro.entrada,
            salida=self.salida + otro.salida,
            cache_lectura=self.cache_lectura + otro.cache_lectura,
            cache_escritura=self.cache_escritura + otro.cache_escritura,
        )


class RespuestaModelo(_Modelo):
    bloques: list[Bloque]
    motivo: MotivoFin
    uso: Uso
    modelo: str  # qué modelo respondió de verdad
    crudo: list[dict[str, Any]] = Field(default_factory=list)  # ver `Mensaje.crudo`
    id_solicitud: str | None = None  # para reportarle un problema al proveedor

    @property
    def texto(self) -> str:
        """Todo el texto de la respuesta, unido."""
        return "".join(b.texto for b in self.bloques if isinstance(b, BloqueTexto))

    @property
    def llamadas(self) -> list[LlamadaHerramienta]:
        """Las herramientas que el modelo pidió, en orden."""
        return [b for b in self.bloques if isinstance(b, LlamadaHerramienta)]

    def como_mensaje(self) -> Mensaje:
        """La respuesta como mensaje del asistente, para agregarla a la conversación."""
        return Mensaje(rol=Rol.ASISTENTE, bloques=self.bloques, crudo=self.crudo or None)


# ---------- Herramientas para el modelo ----------


class DefinicionHerramienta(_Modelo):
    """Lo que el modelo sabe de una herramienta: su nombre, para qué sirve y sus argumentos."""

    nombre: str
    descripcion: str
    parametros: dict[str, Any]  # JSON Schema generado por Pydantic (`Any`: es JSON)


def definiciones_desde_registro(registro: Registro) -> list[DefinicionHerramienta]:
    """Las definiciones de TODAS las herramientas del registro, en orden alfabético.

    Salen del mismo código que las valida: si se agrega un argumento a una herramienta,
    el modelo lo ve automáticamente. El orden es fijo para que la caché del prompt
    funcione (si el orden cambiara, la caché se invalidaría en cada llamada).
    """
    return [
        DefinicionHerramienta(
            nombre=h.nombre, descripcion=h.descripcion, parametros=h.esquema_parametros()
        )
        for h in registro.listar()
    ]


# ---------- Errores y contrato ----------


class ErrorDelModelo(Exception):
    """El proveedor no pudo responder. El mensaje es para personas: nunca lleva la clave.

    `reintentable`: True si es un problema pasajero (vale la pena intentar de nuevo más
    tarde) y False si hay que corregir algo (la clave, el modelo, la solicitud).
    """

    def __init__(self, mensaje: str, *, reintentable: bool, codigo: str) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.reintentable = reintentable
        self.codigo = codigo  # corto, para logs: "timeout", "autenticacion", "saturado"...


class AdaptadorLLM(Protocol):
    """Lo que el agente necesita de un modelo de lenguaje. Nada más.

    Un `Protocol` es un "contrato por forma": cualquier clase con estos atributos y este
    método sirve, sin heredar de nada. Así el adaptador real (Anthropic) y el falso (de
    las pruebas) son intercambiables.
    """

    @property
    def modelo(self) -> str:
        """El modelo configurado, por ejemplo "claude-haiku-5-5"."""
        ...

    def enviar(
        self,
        sistema: str,
        mensajes: Sequence[Mensaje],
        herramientas: Sequence[DefinicionHerramienta],
    ) -> RespuestaModelo:
        """Envía la conversación y devuelve la respuesta. Lanza `ErrorDelModelo` si falla."""
        ...
