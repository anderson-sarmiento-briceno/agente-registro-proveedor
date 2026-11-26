"""Evaluaciones del agente con el modelo REAL (Paso 17).

Uso:
    uv run python scripts/evaluar.py                      # los 9 escenarios
    uv run python scripts/evaluar.py --esfuerzo low       # comparar el esfuerzo (CA6)
    uv run python scripts/evaluar.py --escenario E3       # solo uno (se puede repetir)
    uv run python scripts/evaluar.py --tope-usd 0.10      # otro tope de dinero

Necesita la clave de Anthropic en `.env`. GASTA DINERO (poco: una corrida completa con
claude-haiku-5-5 son unos centavos de dólar), por eso no corre en pytest ni en el CI.
El reporte queda en `evals/reportes/`. Nunca imprime la clave.

La lógica está en `registro_proveedor.evaluacion`.
"""

import io
import sys

from registro_proveedor.config import cargar_configuracion
from registro_proveedor.evaluacion.evaluador import principal
from registro_proveedor.observabilidad import configurar_logs

if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    # Solo errores en la terminal: los avisos esperados (por ejemplo, la instrucción
    # sospechosa del escenario E6) ya quedan en el reporte.
    configurar_logs("ERROR")
    sys.exit(principal(sys.argv[1:], config=cargar_configuracion()))
