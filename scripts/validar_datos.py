"""Valida todos los insumos de `datos/` e imprime el reporte.

Uso:
    uv run python scripts/validar_datos.py            # valida datos/
    uv run python scripts/validar_datos.py otra/ruta  # valida otra carpeta

Termina con código 0 si no hay errores (las sugerencias no cuentan) y con 1 si los hay,
para que el CI falle cuando un dato está roto.
"""

import io
import sys
from pathlib import Path

from registro_proveedor.config import RAIZ_PROYECTO
from registro_proveedor.dominio.validacion import formatear_reporte, validar_datos


def main(argumentos: list[str]) -> int:
    # En Windows, la salida redirigida puede no ser UTF-8 y romper las tildes.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    datos = Path(argumentos[0]) if argumentos else RAIZ_PROYECTO / "datos"
    reporte = validar_datos(datos)
    print(formatear_reporte(reporte))
    return 0 if reporte.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
