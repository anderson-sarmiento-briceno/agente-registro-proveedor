"""Adaptador para Anthropic (Claude), con el SDK oficial `anthropic`.

Traduce entre nuestros tipos (`adaptador.py`) y los de Anthropic, en dos funciones puras
(fáciles de probar sin red):
    - `construir_solicitud`: nuestra conversación + herramientas → parámetros de la API.
    - `convertir_respuesta`: la respuesta de la API → `RespuestaModelo`.

Qué se le pide a la API en cada llamada:
    - `model`: LLM_MODELO (por defecto claude-haiku-5-5).
    - `output_config.effort`: LLM_ESFUERZO (CA6, ajustada: reemplaza a `temperature`, que
      el modelo y la versión actual de la API rechazan).
    - `cache_control`: caché automática (CA7). El prompt y las herramientas se repiten en
      cada llamada; desde la segunda vez se cobran mucho más barato.
    - `thinking`: no se envía. En claude-haiku-5-5 el razonamiento adaptativo viene
      activado, y el modelo decide cuánto pensar.

Timeout y reintentos: los maneja el SDK (`timeout`, `max_retries`), que reintenta solo
los errores pasajeros (conexión, 408, 409, 429 y 5xx), esperando cada vez un poco más.
No se reescribe esa lógica: se configura.
"""

from collections.abc import Sequence
from typing import Any, cast

import anthropic
from anthropic import DefaultHttpxClient
from anthropic.types import (
    CacheControlEphemeralParam,
    ContentBlockParam,
    Message,
    MessageParam,
    OutputConfigParam,
    ToolParam,
)

from registro_proveedor.agente.llm.adaptador import (
    AdaptadorLLM,
    Bloque,
    BloqueTexto,
    DefinicionHerramienta,
    ErrorDelModelo,
    LlamadaHerramienta,
    Mensaje,
    MotivoFin,
    RespuestaModelo,
    Rol,
    Uso,
)
from registro_proveedor.config import Configuracion

# Cómo se llama cada motivo de fin en la API de Anthropic → el nuestro.
MOTIVOS = {
    "end_turn": MotivoFin.TERMINO,
    "stop_sequence": MotivoFin.TERMINO,
    "tool_use": MotivoFin.PIDE_HERRAMIENTA,
    "max_tokens": MotivoFin.LIMITE_TOKENS,
    "model_context_window_exceeded": MotivoFin.LIMITE_TOKENS,
    "pause_turn": MotivoFin.PAUSA,
    "refusal": MotivoFin.RECHAZO,
}


class AdaptadorAnthropic:
    """La implementación de `AdaptadorLLM` para Anthropic."""

    def __init__(
        self,
        *,
        modelo: str,
        esfuerzo: str,
        max_tokens: int,
        cliente: anthropic.Anthropic,
    ) -> None:
        self._modelo = modelo
        self._esfuerzo = esfuerzo
        self._max_tokens = max_tokens
        self._cliente = cliente

    @classmethod
    def desde_configuracion(
        cls, config: Configuracion, http_client: DefaultHttpxClient | None = None
    ) -> "AdaptadorAnthropic":
        """El adaptador con la configuración del proyecto (.env).

        La clave se pasa al SDK solo si está en la configuración. Si no está, el SDK la
        busca por su cuenta (variable de entorno o perfil de `ant auth login`).
        `http_client` permite a las pruebas simular las respuestas sin red.
        """
        secreto = config.anthropic_api_key
        clave = secreto.get_secret_value() if secreto is not None else ""
        try:
            cliente = anthropic.Anthropic(
                api_key=clave or None,  # None = que el SDK la busque por su cuenta
                timeout=config.llm_timeout_s,
                max_retries=config.llm_reintentos,
                http_client=http_client,
            )
        except anthropic.AnthropicError:
            raise ErrorDelModelo(
                "no hay una clave de Anthropic configurada: póngala en ANTHROPIC_API_KEY "
                "dentro del archivo .env",
                reintentable=False,
                codigo="sin_clave",
            ) from None
        return cls(
            modelo=config.llm_modelo,
            esfuerzo=config.llm_esfuerzo,
            max_tokens=config.llm_max_tokens,
            cliente=cliente,
        )

    @property
    def modelo(self) -> str:
        return self._modelo

    def enviar(
        self,
        sistema: str,
        mensajes: Sequence[Mensaje],
        herramientas: Sequence[DefinicionHerramienta],
    ) -> RespuestaModelo:
        """Envía la conversación a Claude. Lanza `ErrorDelModelo` con un mensaje claro si falla."""
        try:
            respuesta = self._cliente.messages.create(
                model=self._modelo,
                max_tokens=self._max_tokens,
                system=sistema,
                messages=convertir_mensajes(mensajes),
                tools=convertir_herramientas(herramientas),
                output_config=cast(OutputConfigParam, {"effort": self._esfuerzo}),
                cache_control=CacheControlEphemeralParam(type="ephemeral"),
            )
        except anthropic.APIError as e:
            raise traducir_error(e, self._modelo) from None
        except TypeError as e:
            # Sin ninguna credencial, el SDK no lanza uno de sus errores: lanza un TypeError
            # ("Could not resolve authentication method"), ANTES de llamar a la red. Se
            # traduce para que el agente muestre un mensaje claro en vez de caerse.
            # Cualquier otro TypeError es un error de programación y se deja pasar.
            if "authentication" not in str(e):
                raise
            raise ErrorDelModelo(
                "no hay una clave de Anthropic configurada: póngala en ANTHROPIC_API_KEY "
                "dentro del archivo .env",
                reintentable=False,
                codigo="sin_clave",
            ) from None
        return convertir_respuesta(respuesta)


# ---------- De nuestros tipos a los de Anthropic ----------


def convertir_herramientas(herramientas: Sequence[DefinicionHerramienta]) -> list[ToolParam]:
    """Cada herramienta como la espera Anthropic: nombre, descripción y esquema de argumentos."""
    return [
        ToolParam(
            name=h.nombre,
            description=h.descripcion,
            input_schema=cast(Any, h.parametros),  # JSON Schema de Pydantic, ya válido
        )
        for h in herramientas
    ]


def convertir_mensajes(mensajes: Sequence[Mensaje]) -> list[MessageParam]:
    """Nuestra conversación en el formato de Anthropic.

    Un mensaje del asistente que trae `crudo` (lo produjo este mismo adaptador) se
    devuelve TAL CUAL: Anthropic exige recibir sin cambios los bloques de razonamiento
    ("thinking") de sus respuestas anteriores.
    """
    convertidos: list[MessageParam] = []
    for m in mensajes:
        if m.rol is Rol.ASISTENTE:
            contenido = (
                cast(list[ContentBlockParam], m.crudo)
                if m.crudo
                else [_bloque(b) for b in m.bloques]
            )
            convertidos.append({"role": "assistant", "content": contenido})
        else:
            convertidos.append({"role": "user", "content": [_bloque(b) for b in m.bloques]})
    return convertidos


def _bloque(bloque: Bloque) -> ContentBlockParam:
    if isinstance(bloque, BloqueTexto):
        return {"type": "text", "text": bloque.texto}
    if isinstance(bloque, LlamadaHerramienta):
        return {
            "type": "tool_use",
            "id": bloque.id,
            "name": bloque.nombre,
            "input": bloque.argumentos,
        }
    return {
        "type": "tool_result",
        "tool_use_id": bloque.id_llamada,
        "content": bloque.contenido,
        "is_error": bloque.es_error,
    }


# ---------- De Anthropic a nuestros tipos ----------


def convertir_respuesta(respuesta: Message) -> RespuestaModelo:
    """La respuesta de Anthropic como `RespuestaModelo`.

    En `bloques` quedan solo el texto y los pedidos de herramienta (lo que entiende el
    agente). TODO el contenido original queda en `crudo`, incluido el razonamiento del
    modelo, para devolverlo tal cual en la siguiente llamada.
    """
    bloques: list[Bloque] = []
    for b in respuesta.content:
        if b.type == "text":
            bloques.append(BloqueTexto(texto=b.text))
        elif b.type == "tool_use":
            bloques.append(LlamadaHerramienta(id=b.id, nombre=b.name, argumentos=dict(b.input)))
    uso = respuesta.usage
    return RespuestaModelo(
        bloques=bloques,
        motivo=MOTIVOS.get(str(respuesta.stop_reason), MotivoFin.TERMINO),
        uso=Uso(
            entrada=uso.input_tokens,
            salida=uso.output_tokens,
            cache_lectura=uso.cache_read_input_tokens or 0,
            cache_escritura=uso.cache_creation_input_tokens or 0,
        ),
        modelo=respuesta.model,
        crudo=[b.model_dump(mode="json", exclude_none=True) for b in respuesta.content],
        id_solicitud=getattr(respuesta, "_request_id", None),
    )


# ---------- Errores ----------


def traducir_error(e: anthropic.APIError, modelo: str) -> ErrorDelModelo:
    """Un error del SDK como `ErrorDelModelo`, con un mensaje claro y sin datos sensibles.

    El orden importa: primero los casos más específicos. Por ejemplo, `APITimeoutError`
    es un tipo de `APIConnectionError`, así que debe revisarse antes.
    Cuando llega aquí un error pasajero, el SDK ya hizo sus reintentos.
    """
    if isinstance(e, anthropic.AuthenticationError):
        return ErrorDelModelo(
            "la clave de Anthropic no es válida o falta: "
            "revise ANTHROPIC_API_KEY en el archivo .env",
            reintentable=False,
            codigo="autenticacion",
        )
    if isinstance(e, anthropic.PermissionDeniedError):
        return ErrorDelModelo(
            "la clave de Anthropic no tiene permiso para usar este modelo",
            reintentable=False,
            codigo="permiso",
        )
    if isinstance(e, anthropic.NotFoundError):
        return ErrorDelModelo(
            f"no existe el modelo «{modelo}»: revise LLM_MODELO en el archivo .env",
            reintentable=False,
            codigo="modelo_inexistente",
        )
    if isinstance(e, anthropic.RateLimitError):
        return ErrorDelModelo(
            "se alcanzó el límite de uso del modelo: intente de nuevo en un momento",
            reintentable=True,
            codigo="limite_de_uso",
        )
    if isinstance(e, anthropic.BadRequestError):
        return ErrorDelModelo(
            f"el modelo rechazó la solicitud: {e.message[:200]}",
            reintentable=False,
            codigo="solicitud_invalida",
        )
    if isinstance(e, anthropic.APITimeoutError):
        return ErrorDelModelo(
            "el modelo tardó demasiado en responder: intente de nuevo en un momento",
            reintentable=True,
            codigo="timeout",
        )
    if isinstance(e, anthropic.APIConnectionError):
        return ErrorDelModelo(
            "no hay conexión con el servicio del modelo: revise la conexión a internet",
            reintentable=True,
            codigo="sin_conexion",
        )
    if isinstance(e, anthropic.APIStatusError) and e.status_code >= 500:
        return ErrorDelModelo(
            "el servicio del modelo está saturado o tuvo una falla: intente de nuevo en un momento",
            reintentable=True,
            codigo="servicio_no_disponible",
        )
    estado = e.status_code if isinstance(e, anthropic.APIStatusError) else "?"
    return ErrorDelModelo(
        f"el modelo respondió con un error inesperado (código {estado})",
        reintentable=False,
        codigo=f"http_{estado}",
    )


def _cumple_el_contrato(adaptador: AdaptadorAnthropic) -> AdaptadorLLM:
    """No se llama nunca: existe para que mypy compruebe que la clase cumple `AdaptadorLLM`.

    Si a `AdaptadorAnthropic` le faltara `modelo` o `enviar`, o tuvieran otra forma,
    mypy marcaría un error aquí.
    """
    return adaptador
