"""Arma los datos del piloto (Paso 21): `datos/` + `piloto/casos/` → `piloto/datos-del-piloto/`.

Uso:
    uv run python scripts/preparar_piloto.py

Después, en `.env`:  CARPETA_DATOS=piloto/datos-del-piloto   (y reiniciar uvicorn).
La guía completa del piloto está en `piloto/GUIA.md`.
"""

import io
import sys

from registro_proveedor.dominio.validacion import formatear_reporte
from registro_proveedor.piloto.preparar import DATOS_DEL_PILOTO, casos_del_piloto, preparar

if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    reporte = preparar()
    print(formatear_reporte(reporte))
    print(f"\nCasos nuevos del piloto: {', '.join(casos_del_piloto())}")
    print(f"Carpeta armada: {DATOS_DEL_PILOTO}")
    print("En .env: CARPETA_DATOS=piloto/datos-del-piloto  (y reinicie uvicorn)")
    sys.exit(0 if reporte.ok else 1)
