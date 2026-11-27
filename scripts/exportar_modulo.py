"""Exporta el módulo reutilizable a `modulo/` (Paso 20): agent.md, SKILL.md y LEEME.md.

Uso:
    uv run python scripts/exportar_modulo.py

Hay que correrlo cada vez que cambie `agente/prompt.md` o `knowledge/`: una prueba
revisa que `modulo/` esté al día y falla si no.

La lógica está en `registro_proveedor.reutilizable.exportar`.
"""

import io
import sys

from registro_proveedor.config import RAIZ_PROYECTO
from registro_proveedor.reutilizable.exportar import exportar

if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    for ruta in exportar():
        print(f"escrito: {ruta.relative_to(RAIZ_PROYECTO).as_posix()}")
