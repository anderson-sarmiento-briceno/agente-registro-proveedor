"""Valida todos los insumos de `datos/` e imprime el reporte de errores y sugerencias.

Uso:
    uv run python scripts/validar_datos.py            # valida datos/
    uv run python scripts/validar_datos.py otra/ruta  # valida otra carpeta (útil para pruebas)

Código de salida (lo que el CI mira para decidir si falla):
    0 → no hay errores (puede haber sugerencias: no cuentan)
    1 → hay al menos un error

Este archivo es solo la "puerta de entrada" desde la terminal: toda la lógica está en
`registro_proveedor.dominio.validacion`, que es lo que se prueba.
"""

import io
import sys
from pathlib import Path

from registro_proveedor.config import RAIZ_PROYECTO
from registro_proveedor.dominio.validacion import formatear_reporte, validar_datos


def main(argumentos: list[str]) -> int:
    # En Windows, cuando la salida se redirige (a un archivo o al CI), Python puede
    # usar una codificación que no es UTF-8, y las tildes y las «» saldrían rotas.
    # Se fuerza UTF-8. El `isinstance` es necesario porque `sys.stdout` podría haber
    # sido reemplazado por otro objeto que no tenga `reconfigure`.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    datos = Path(argumentos[0]) if argumentos else RAIZ_PROYECTO / "datos"
    reporte = validar_datos(datos)
    print(formatear_reporte(reporte))
    return 0 if reporte.ok else 1


# Este bloque solo se ejecuta cuando el archivo se corre directamente
# (`python scripts/validar_datos.py`), no cuando otro archivo lo importa.
# `sys.argv[1:]` son los argumentos escritos después del nombre del script.
if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
