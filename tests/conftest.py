"""Fixtures compartidas por las pruebas."""

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.ayudas import DATOS_REALES, EditarJson


@pytest.fixture
def datos(tmp_path: Path) -> Path:
    """Copia temporal de `datos/` para poder romperla sin tocar los datos reales."""
    copia = tmp_path / "datos"
    shutil.copytree(DATOS_REALES, copia)
    return copia


@pytest.fixture
def editar_json(datos: Path) -> EditarJson:
    def editar(relativa: str, cambio: Callable[[object], object]) -> None:
        ruta = datos / relativa
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
        ruta.write_text(json.dumps(cambio(contenido), ensure_ascii=False), encoding="utf-8")

    return editar
