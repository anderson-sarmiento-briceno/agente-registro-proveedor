"""Fixtures compartidas por las pruebas.

¿Qué es una fixture?
    Algo que una prueba necesita y que pytest prepara antes de ejecutarla. La prueba
    lo pide poniendo su nombre como parámetro:

        def test_algo(datos: Path) -> None:   # pytest llama a la fixture `datos`
            ...

    pytest busca las fixtures en este archivo de forma automática: no hace falta
    importarlo.

¿Por qué copiar `datos/`?
    Muchas pruebas rompen un archivo a propósito para ver si el error se detecta.
    `datos/` no se puede modificar nunca, así que se trabaja sobre una copia en una
    carpeta temporal (`tmp_path`), que pytest crea nueva para cada prueba y borra
    después. Así una prueba no afecta a otra.
"""

import json
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import structlog

from registro_proveedor.herramientas.base import Contexto
from tests.ayudas import DATOS_REALES, FECHA_FIJA, HORA_FIJA, EditarJson


@pytest.fixture
def datos(tmp_path: Path) -> Path:
    """Copia temporal de `datos/` para poder romperla sin tocar los datos reales.

    La copia se llama también "datos", para que los mensajes del reporte muestren
    las mismas rutas que con los datos reales ("datos/casos/...").
    """
    copia = tmp_path / "datos"
    shutil.copytree(DATOS_REALES, copia)
    return copia


@pytest.fixture
def editar_json(datos: Path) -> EditarJson:
    """Función para modificar un JSON de la copia temporal en una sola línea.

    Ejemplo: cambiar el formato de una solicitud a un valor inválido.

        editar_json("casos/x/solicitud.json", lambda s: {**como_dict(s), "formato": "excel"})

    (`{**d, "formato": "excel"}` crea un diccionario igual a `d`, pero con ese campo cambiado.)
    """

    def editar(relativa: str, cambio: Callable[[object], object]) -> None:
        ruta = datos / relativa
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
        # ensure_ascii=False: guarda las tildes tal cual, no como "ó".
        ruta.write_text(json.dumps(cambio(contenido), ensure_ascii=False), encoding="utf-8")

    return editar


@pytest.fixture
def contexto(tmp_path: Path) -> Contexto:
    """Contexto de herramienta para pruebas: lee los datos reales y escribe en un `out/` temporal.

    La fecha y la hora son fijas, para que el resultado (y el log) sea siempre igual,
    sin importar el día en que se ejecuten las pruebas (RN7).
    """
    return Contexto(
        datos=DATOS_REALES,
        salida=tmp_path / "out",
        fecha_ejecucion=FECHA_FIJA,
        sesion_id="sesion-de-prueba",
        reloj=lambda: HORA_FIJA,
    )


@pytest.fixture(autouse=True)
def _restaurar_structlog() -> Iterator[None]:
    """Deja structlog como estaba después de cada prueba.

    `autouse=True`: se aplica a todas las pruebas sin pedirla. Hace falta porque
    `configurar_logs` cambia una configuración global, y una prueba no debe afectar
    a las siguientes. El `yield` separa el "antes" (nada) del "después" (restaurar).
    """
    yield
    structlog.reset_defaults()
