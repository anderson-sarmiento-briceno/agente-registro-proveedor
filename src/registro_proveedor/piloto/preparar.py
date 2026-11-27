"""Arma la carpeta de datos del piloto: `datos/` + los casos de `piloto/casos/` (Paso 21).

¿Por qué una carpeta aparte?
    Los 4 casos de `datos/` sostienen las pruebas golden, las evaluaciones y la demo
    pública (muchas partes cuentan con que son exactamente esos). Los casos del piloto
    son NUEVOS y más desordenados, a propósito: así se prueba lo que el plan marca como
    riesgo ("plantillas reales peores que las de referencia") sin romper nada.

¿Qué hace?
    1. Copia `datos/` completo (maestro, soportes, glosario y los 4 casos) a
       `piloto/datos-del-piloto/`, que NO se sube a git (es una copia armada).
    2. Le agrega cada caso de `piloto/casos/`.
    3. Valida el resultado con las mismas reglas de `validar_datos.py`.

Para usarla, en `.env`:  CARPETA_DATOS=piloto/datos-del-piloto
"""

import shutil
from pathlib import Path

from registro_proveedor.config import RAIZ_PROYECTO
from registro_proveedor.dominio.validacion import Reporte, validar_datos

CARPETA_PILOTO = RAIZ_PROYECTO / "piloto"
CASOS_DEL_PILOTO = CARPETA_PILOTO / "casos"
NOMBRE_DATOS_DEL_PILOTO = "datos-del-piloto"
DATOS_DEL_PILOTO = CARPETA_PILOTO / NOMBRE_DATOS_DEL_PILOTO


class ErrorDePiloto(Exception):
    """No se pudo armar la carpeta del piloto; el mensaje dice por qué."""


def preparar(
    destino: Path = DATOS_DEL_PILOTO,
    datos: Path = RAIZ_PROYECTO / "datos",
    casos: Path = CASOS_DEL_PILOTO,
) -> Reporte:
    """Arma `destino` (borrándolo antes) y devuelve el reporte de validación."""
    # Por seguridad, solo se borra una carpeta con ese nombre (como `out` en la demo).
    if destino.resolve().name != NOMBRE_DATOS_DEL_PILOTO:
        raise ErrorDePiloto(
            f"por seguridad, la carpeta debe llamarse «{NOMBRE_DATOS_DEL_PILOTO}» "
            f"(se recibió «{destino}»)"
        )
    shutil.rmtree(destino, ignore_errors=True)
    shutil.copytree(datos, destino)
    for caso in sorted(p for p in casos.iterdir() if p.is_dir()):
        llegada = destino / "casos" / caso.name
        if llegada.exists():
            raise ErrorDePiloto(f"el caso «{caso.name}» ya existe en {datos.name}/: cámbiele el id")
        shutil.copytree(caso, llegada)
    return validar_datos(destino)


def casos_del_piloto(casos: Path = CASOS_DEL_PILOTO) -> list[str]:
    """Los ids de los casos nuevos del piloto (sin los 4 de referencia)."""
    return sorted(p.name for p in casos.iterdir() if p.is_dir())
