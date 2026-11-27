"""Demostración sin modelo de lenguaje: procesa los casos de ejemplo de punta a punta.

Uso:
    uv run python scripts/demo.py                          # los 4 casos, con la fecha de hoy
    uv run python scripts/demo.py --fecha 2026-09-01       # con otra fecha (como las pruebas)
    uv run python scripts/demo.py --caso ec-corp-andina    # un solo caso

Borra y vuelve a crear `out/`. No necesita clave de Anthropic.

Código de salida: 0 si todas las herramientas respondieron bien (un paquete "no listo"
no es un error) y 1 si alguna falló. El CI lo usa.

Toda la lógica está en `registro_proveedor.demo`; este archivo solo la llama.
"""

import io
import sys

from registro_proveedor.demo import main

if __name__ == "__main__":
    # Tildes y símbolos (✅ ⛔) bien escritos aunque la salida vaya a un archivo o al CI.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    resultado = main(sys.argv[1:])
    print(resultado.texto)
    sys.exit(resultado.codigo)
