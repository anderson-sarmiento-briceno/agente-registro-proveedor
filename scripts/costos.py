"""Costo del modelo por caso, sumado desde `out/costos.jsonl` (Paso 18).

Uso:
    uv run python scripts/costos.py

No llama al modelo ni gasta nada: solo lee lo que dejó cada turno del agente (chat de la
terminal o del navegador). Un turno que trabajó dos casos reparte su costo entre ambos.
"""

import io
import sys

from registro_proveedor.config import RAIZ_PROYECTO
from registro_proveedor.observabilidad import costo_por_caso, tabla_de_costos

if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    print(tabla_de_costos(costo_por_caso(RAIZ_PROYECTO / "out")))
