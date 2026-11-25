"""Observabilidad: registro de llamadas (auditoría), logs de operación y enmascaramiento.

Dos tipos de log, con propósitos distintos:

1. **Auditoría** (`log.jsonl`, RN5 y CA4): una línea JSON por cada llamada a una
   herramienta, con `{ts, sesion, herramienta, caso, ok, resumen, duracion_ms}`.
   Sirve para responder "¿qué hizo el agente en este caso?". Se escribe en dos
   lugares: `out/log.jsonl` (todas las llamadas) y `out/<caso>/log.jsonl` (solo las
   de ese caso, para auditarlo por separado).

2. **Operación** (structlog, en JSON por la terminal): para depurar. Por ejemplo,
   cuando una herramienta falla de forma inesperada, aquí queda el detalle técnico
   del error, que nunca se le muestra al modelo ni a la usuaria.

Enmascaramiento (RN8):
    Los datos sensibles (número de cuenta bancaria e identificación personal del
    representante legal) se muestran como `****2345`: solo los últimos 4 caracteres.
    El NIT NO se enmascara: es de la empresa, es público y el resumen lo necesita.
"""

import json
import logging
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

import structlog
from pydantic import BaseModel, ConfigDict
from structlog.typing import EventDict, FilteringBoundLogger, WrappedLogger

# ---------- Enmascaramiento ----------

# Nombres de campo cuyo valor siempre se enmascara, estén donde estén (en el maestro,
# en un log, en la respuesta de una herramienta).
CAMPOS_SENSIBLES = frozenset({"numero_cuenta", "identificacion"})

# Las mismas, como rutas del maestro. El mapeo (Paso 5) las usará para enmascarar el
# valor de un campo como "Número de cuenta", cuyo nombre en la respuesta es `valor`
# (y por eso no lo detectaría `CAMPOS_SENSIBLES`).
RUTAS_SENSIBLES = frozenset({"banco.numero_cuenta", "representante_legal.identificacion"})

CARACTERES_VISIBLES = 4


def enmascarar(valor: object) -> str:
    """Oculta un valor dejando ver solo sus últimos 4 caracteres: "03100012345" → "****2345".

    Si el valor tiene 4 caracteres o menos, se oculta entero ("****"): mostrar los
    últimos 4 sería mostrarlo completo.
    """
    texto = str(valor)
    if len(texto) <= CARACTERES_VISIBLES:
        return "****"
    return "****" + texto[-CARACTERES_VISIBLES:]


def es_ruta_sensible(ruta: str) -> bool:
    """True si la ruta del maestro apunta a un dato sensible ("banco.numero_cuenta")."""
    return ruta in RUTAS_SENSIBLES


def enmascarar_datos(valor: object) -> object:
    """Copia de un dato JSON con los campos sensibles enmascarados (recorre todo).

    Entra en los diccionarios y en las listas a cualquier profundidad. Por ejemplo,
    {"banco": {"numero_cuenta": "03100012345"}} → {"banco": {"numero_cuenta": "****2345"}}.
    No modifica el original: devuelve uno nuevo.
    """
    if isinstance(valor, Mapping):
        return {
            clave: (
                enmascarar(contenido)
                if clave in CAMPOS_SENSIBLES and contenido is not None
                else enmascarar_datos(contenido)
            )
            for clave, contenido in valor.items()
        }
    if isinstance(valor, list):
        return [enmascarar_datos(elemento) for elemento in valor]
    return valor


# ---------- Auditoría: log.jsonl ----------

ARCHIVO_AUDITORIA = "log.jsonl"


class RegistroLlamada(BaseModel):
    """Una línea de `log.jsonl`: qué herramienta se llamó, cuándo, y cómo terminó."""

    model_config = ConfigDict(frozen=True)

    ts: datetime
    sesion: str
    herramienta: str
    caso: str | None
    ok: bool
    resumen: str  # una frase; nunca datos sensibles completos
    duracion_ms: int


def escribir_auditoria(salida: Path, registro: RegistroLlamada) -> None:
    """Agrega la llamada a `out/log.jsonl` y, si hay caso, a `out/<caso>/log.jsonl`.

    "jsonl" = una línea JSON por llamada. Se abre en modo "a" (append): se agrega al
    final, nunca se borra lo anterior.

    Si no se puede escribir (disco lleno, permisos), NO se interrumpe la herramienta:
    perder una línea de auditoría es malo, pero peor sería que la analista no pueda
    trabajar. El problema queda en el log de operación.
    """
    linea = json.dumps(enmascarar_datos(registro.model_dump(mode="json")), ensure_ascii=False)
    destinos = [salida / ARCHIVO_AUDITORIA]
    if registro.caso is not None:
        destinos.append(salida / registro.caso / ARCHIVO_AUDITORIA)
    for destino in destinos:
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            with destino.open("a", encoding="utf-8", newline="\n") as archivo:
                archivo.write(linea + "\n")
        except OSError as e:
            obtener_logger().warning(
                "no_se_pudo_escribir_auditoria", archivo=str(destino), error=str(e)
            )


# ---------- Operación: structlog ----------


def procesador_enmascarar(_logger: WrappedLogger, _metodo: str, evento: EventDict) -> EventDict:
    """Paso de structlog que enmascara los campos sensibles de cada evento antes de escribirlo.

    structlog procesa cada mensaje con una cadena de funciones ("procesadores"),
    cada una recibe el evento y devuelve el evento modificado. Esta es una de ellas.
    """
    enmascarado = enmascarar_datos(dict(evento))
    assert isinstance(enmascarado, dict)  # siempre lo es: la entrada es un diccionario
    return enmascarado


def configurar_logs(nivel: str = "INFO") -> None:
    """Configura los logs de operación: JSON, por la salida de errores (stderr).

    Se llama una vez al arrancar (servidor o demo). Sin esto, structlog usa su
    configuración por defecto (texto con colores), que sirve igual para las pruebas.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            # El detalle de las excepciones, como datos. `show_locals=False` es
            # importante: por defecto se incluirían los valores de las variables
            # locales, que podrían ser datos sensibles completos.
            structlog.processors.ExceptionRenderer(
                structlog.tracebacks.ExceptionDictTransformer(show_locals=False)
            ),
            procesador_enmascarar,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(nivel)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )


def obtener_logger() -> FilteringBoundLogger:
    """El logger de operación del proyecto."""
    logger: FilteringBoundLogger = structlog.get_logger("registro_proveedor")
    return logger
