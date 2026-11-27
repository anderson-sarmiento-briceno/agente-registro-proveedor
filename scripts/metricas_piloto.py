"""Calcula las métricas del piloto (Paso 21) y escribe `piloto/reporte.md`.

Uso (después de trabajar los casos en el chat local y de llenar `piloto/planilla.md`):
    uv run python scripts/metricas_piloto.py

No llama al modelo ni gasta nada: lee lo que el sistema ya registró en `out/`. Usa la
carpeta de datos de `CARPETA_DATOS` (la del piloto), para comparar con su maestro.

La lógica está en `registro_proveedor.piloto.metricas`.
"""

import io
import sys
from datetime import datetime

from registro_proveedor.config import RAIZ_PROYECTO, cargar_configuracion
from registro_proveedor.piloto.metricas import medir, reporte
from registro_proveedor.piloto.preparar import CARPETA_PILOTO

if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    config = cargar_configuracion()
    piloto = medir(
        salida=RAIZ_PROYECTO / "out",
        datos=config.datos_efectivos(),
        esperado=CARPETA_PILOTO / "esperado",
        planilla=CARPETA_PILOTO / "planilla.md",
    )
    destino = CARPETA_PILOTO / "reporte.md"
    destino.write_text(reporte(piloto, datetime.now()), encoding="utf-8", newline="\n")
    print(f"Casos medidos: {len(piloto.casos)} · reporte en {destino.relative_to(RAIZ_PROYECTO)}")
