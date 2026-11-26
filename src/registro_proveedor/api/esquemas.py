"""El contrato de la API: qué recibe y qué devuelve cada endpoint (sección 12 del plan).

¿Por qué en inglés, si el resto del código está en español?
    Es el contrato PÚBLICO de la API, y el plan lo escribió así (`session_id`,
    `message`, `reply`, `tool_calls`). Lo que va por dentro (el ciclo, las herramientas)
    sigue en español. Este archivo es el único punto donde se traduce.

¿De dónde sale cada respuesta?
    Siempre de un `Turno` del ciclo (`de_turno`), NUNCA del historial crudo de la
    sesión. Así la API solo muestra lo que vio la analista: la respuesta ya revisada
    por el guardarraíl (Paso 14), los argumentos enmascarados y los resúmenes de
    log.jsonl. Ningún resultado completo de herramienta sale por aquí.

Pydantic valida la entrada (por ejemplo, un `message` vacío o de más de 4 000
caracteres se rechaza) y FastAPI usa estos mismos modelos para la documentación
OpenAPI de `/docs`.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from registro_proveedor.agente.ciclo import (
    Alerta,
    ConfirmacionPendiente,
    EstadoLlamada,
    FinTurno,
    LlamadaEjecutada,
    Turno,
)
from registro_proveedor.agente.llm.adaptador import Uso

# Un id de sesión es un uuid en hexadecimal (32 caracteres); uno de confirmación, 8.
PATRON_SESION = r"^[0-9a-f]{32}$"
PATRON_CONFIRMACION = r"^[0-9a-f]{8}$"
LARGO_MAXIMO_MENSAJE = 4000

IdSesion = Annotated[str, Field(pattern=PATRON_SESION, description="Id de la sesión.")]


class _Entrada(BaseModel):
    # Un campo desconocido en la solicitud se rechaza (como en las herramientas).
    model_config = ConfigDict(extra="forbid")


class _Salida(BaseModel):
    model_config = ConfigDict(frozen=True)


# ---------- Entradas ----------


class ChatRequest(_Entrada):
    session_id: IdSesion | None = Field(
        default=None, description="Sin él, se crea una sesión nueva y se devuelve su id."
    )
    message: str = Field(min_length=1, max_length=LARGO_MAXIMO_MENSAJE)

    @field_validator("message")
    @classmethod
    def _no_vacio(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("el mensaje está vacío")
        return valor.strip()


class ConfirmationRequest(_Entrada):
    # Se pide la sesión además del id de la confirmación (que es corto): así nadie
    # puede aprobar la confirmación de OTRA conversación adivinando un id.
    session_id: IdSesion
    approve: bool = Field(description="true = Aprobar · false = Rechazar.")


# ---------- Salidas ----------

# Los estados y motivos internos, en el idioma del contrato.
ESTADOS: dict[EstadoLlamada, str] = {
    EstadoLlamada.EJECUTADA: "executed",
    EstadoLlamada.FALLO: "failed",
    EstadoLlamada.PENDIENTE: "pending",
    EstadoLlamada.APROBADA: "approved",
    EstadoLlamada.RECHAZADA: "rejected",
}
MOTIVOS: dict[FinTurno, str] = {
    FinTurno.RESPONDIO: "answered",
    FinTurno.TOPE_ITERACIONES: "iteration_limit",
    FinTurno.TOPE_TOKENS: "token_limit",
    FinTurno.ERROR_MODELO: "model_error",
    FinTurno.INCOMPLETA: "incomplete",
    FinTurno.RECHAZO: "refused",
    FinTurno.CONFIRMACION_INVALIDA: "invalid_confirmation",
}


class ToolCall(_Salida):
    """Una herramienta que pidió el modelo, en el orden en que se ejecutó."""

    order: int
    name: str
    arguments: dict[str, JsonValue]  # enmascarados
    status: Literal["executed", "failed", "pending", "approved", "rejected"]
    ok: bool
    summary: str  # la misma frase de log.jsonl


class Confirmation(_Salida):
    id: str
    tool: str
    description: str


class Alert(_Salida):
    tool: str
    kinds: list[str]


class Usage(_Salida):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int


class ChatResponse(_Salida):
    session_id: str
    reply: str
    finish_reason: str
    tool_calls: list[ToolCall]
    needs_confirmation: bool
    confirmation_id: str | None  # la primera pendiente (como pide el plan)
    confirmations: list[Confirmation]  # TODAS las pendientes, para los botones
    cancelled: list[Confirmation]  # las que se cancelaron al escribir sin aprobar (RN4)
    alerts: list[Alert]  # resultados con texto que parece una instrucción (Paso 14)
    hidden_values: int  # cuántos datos no verificados se ocultaron de `reply`
    usage: Usage


class TurnRecord(_Salida):
    """Un turno del historial, tal como lo vio la analista."""

    at: datetime
    kind: Literal["message", "approve", "reject"]
    input: str  # el mensaje de la analista, o el id de la confirmación resuelta
    response: ChatResponse


class SessionResponse(_Salida):
    session_id: str
    created_at: datetime
    turns: list[TurnRecord]
    pending: list[Confirmation]
    usage: Usage


class HealthResponse(_Salida):
    ok: bool
    provider: str
    model: str
    llm_configured: bool  # sin la clave: nunca se dice cuál es
    prompt_version: str


class ErrorResponse(_Salida):
    detail: str


# ---------- De los tipos del ciclo al contrato ----------


def de_turno(session_id: str, turno: Turno) -> ChatResponse:
    return ChatResponse(
        session_id=session_id,
        reply=turno.texto,
        finish_reason=MOTIVOS[turno.fin],
        tool_calls=[_llamada(ll) for ll in turno.llamadas],
        needs_confirmation=bool(turno.pendientes),
        confirmation_id=turno.pendientes[0].id if turno.pendientes else None,
        confirmations=[de_confirmacion(p) for p in turno.pendientes],
        cancelled=[de_confirmacion(p) for p in turno.canceladas],
        alerts=[_alerta(a) for a in turno.alertas],
        hidden_values=len(turno.ocultos),
        usage=de_uso(turno.uso),
    )


def de_confirmacion(pendiente: ConfirmacionPendiente) -> Confirmation:
    return Confirmation(
        id=pendiente.id, tool=pendiente.herramienta, description=pendiente.descripcion
    )


def de_uso(uso: Uso) -> Usage:
    return Usage(
        input_tokens=uso.entrada,
        output_tokens=uso.salida,
        cache_read_tokens=uso.cache_lectura,
        cache_write_tokens=uso.cache_escritura,
    )


def _llamada(llamada: LlamadaEjecutada) -> ToolCall:
    return ToolCall.model_validate(
        {
            "order": llamada.orden,
            "name": llamada.nombre,
            "arguments": llamada.argumentos,
            "status": ESTADOS[llamada.estado],
            "ok": llamada.ok,
            "summary": llamada.resumen,
        }
    )


def _alerta(alerta: Alerta) -> Alert:
    return Alert(tool=alerta.herramienta, kinds=list(alerta.tipos))
