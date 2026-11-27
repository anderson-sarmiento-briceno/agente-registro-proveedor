"""Servidor MCP del agente "Registro como Proveedor" (Paso 20).

Uso (lo lanza el cliente MCP, no una persona; habla por stdin/stdout):
    uv run python scripts/servidor_mcp.py

Para conectarlo a Claude Code:
    claude mcp add registro-proveedor -- uv run python scripts/servidor_mcp.py

No necesita la clave de Anthropic: el modelo lo pone el cliente que se conecta. Usa la
fecha real (o FECHA_EJECUCION, si está en .env) y escribe en out/, igual que la demo.
Los logs de operación van a stderr: stdout es solo para el protocolo MCP.

La lógica está en `registro_proveedor.reutilizable.servidor_mcp`.
"""

import anyio

from registro_proveedor.config import cargar_configuracion
from registro_proveedor.observabilidad import configurar_logs
from registro_proveedor.reutilizable.servidor_mcp import correr

if __name__ == "__main__":
    config = cargar_configuracion()
    configurar_logs("WARNING")  # a stderr, en JSON: no ensucia el protocolo
    anyio.run(correr, config)
