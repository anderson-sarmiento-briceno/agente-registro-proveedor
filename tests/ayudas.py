"""Constantes y funciones compartidas por las pruebas.

¿Por qué no van en `conftest.py`?
    `conftest.py` es un archivo especial de pytest para las *fixtures* (ver allí).
    pytest lo carga solo y no está pensado para que otros archivos lo importen.
    Lo que las pruebas importan directamente (constantes, tipos y funciones) va aquí.
"""

import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime

from registro_proveedor.config import RAIZ_PROYECTO
from registro_proveedor.herramientas.base import Aprobacion, Contexto
from registro_proveedor.herramientas.proveedor import registro

# Los datos reales del proyecto. Las pruebas que solo LEEN los usan directamente.
# Las que necesitan romper algo usan la fixture `datos`, que es una copia temporal.
DATOS_REALES = RAIZ_PROYECTO / "datos"

# Fecha y hora fijas para las pruebas (RN7): el resultado no depende del día de hoy.
FECHA_FIJA = date(2026, 9, 1)
HORA_FIJA = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

# Tipo de la fixture `editar_json`: una función que recibe
#   1. la ruta del archivo, relativa a `datos/` (por ejemplo "glosario-campos.json"),
#   2. una función que recibe el contenido actual y devuelve el contenido nuevo.
EditarJson = Callable[[str, Callable[[object], object]], None]


def como_dict(valor: object) -> dict[str, object]:
    """Copia de un objeto JSON, comprobando que de verdad sea un diccionario.

    `json.loads` devuelve un tipo genérico. Sin esta comprobación, mypy no dejaría
    usar `valor["campo"]`. Además se devuelve una copia para no modificar el original.
    """
    assert isinstance(valor, dict)
    return dict(valor)


def como_lista(valor: object) -> list[object]:
    """Copia de una lista JSON, comprobando que de verdad sea una lista."""
    assert isinstance(valor, list)
    return list(valor)


def aprobado(ctx: Contexto, herramienta: str, argumentos: dict[str, object]) -> Contexto:
    """Copia del contexto con una aprobación de la analista para ESA herramienta y argumentos.

    Desde el Paso 13, las herramientas que requieren confirmación se niegan a ejecutar
    sin aprobación (doble candado). Las pruebas de esas herramientas la piden así, de
    forma explícita, igual que lo hace el ciclo del agente cuando la analista aprueba.
    Los argumentos se normalizan como lo hace el ciclo (con sus valores por defecto).
    """
    validados = registro.validar_argumentos(herramienta, argumentos)
    assert validados.ok and validados.data is not None, validados.error
    return dataclasses.replace(
        ctx,
        aprobacion=Aprobacion(
            id="aprobacion-de-prueba",
            herramienta=herramienta,
            argumentos=validados.data,
            por=ctx.usuario,
            en=HORA_FIJA,
        ),
    )
