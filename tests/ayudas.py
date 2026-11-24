"""Constantes y funciones compartidas por las pruebas."""

from collections.abc import Callable

from registro_proveedor.config import RAIZ_PROYECTO

DATOS_REALES = RAIZ_PROYECTO / "datos"

# Modifica un JSON de la copia temporal: recibe la ruta relativa a `datos/` y una
# función que recibe el contenido y devuelve el contenido nuevo.
EditarJson = Callable[[str, Callable[[object], object]], None]


def como_dict(valor: object) -> dict[str, object]:
    """Copia de un objeto JSON, con su tipo comprobado."""
    assert isinstance(valor, dict)
    return dict(valor)


def como_lista(valor: object) -> list[object]:
    """Copia de una lista JSON, con su tipo comprobado."""
    assert isinstance(valor, list)
    return list(valor)
