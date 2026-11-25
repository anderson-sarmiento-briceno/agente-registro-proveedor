"""Prueba real del modelo: ¿qué herramienta pide ante una pregunta de la analista?

Uso:
    uv run python scripts/probar_modelo.py
    uv run python scripts/probar_modelo.py "¿Qué le falta al caso de Honduras?"

Necesita la clave de Anthropic en `.env` (ANTHROPIC_API_KEY) y gasta muy poco dinero
(una sola llamada). NO ejecuta ninguna herramienta: solo muestra cuál pidió el modelo.
Nunca imprime la clave.

La lógica está en `registro_proveedor.agente.llm.prueba_real`.
"""

import io
import sys

from registro_proveedor.agente.llm.prueba_real import PREGUNTA_POR_DEFECTO, probar
from registro_proveedor.config import cargar_configuracion

if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    pregunta = " ".join(sys.argv[1:]) or PREGUNTA_POR_DEFECTO
    codigo, texto = probar(cargar_configuracion(), pregunta)
    print(texto)
    sys.exit(codigo)
