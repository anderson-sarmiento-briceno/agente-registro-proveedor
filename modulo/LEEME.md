# Módulo reutilizable · Registro como Proveedor

Estas piezas son **las mismas** que usa la aplicación (no son copias aparte): se generan
con `uv run python scripts/exportar_modulo.py` y una prueba revisa que estén al día.

| Archivo | Qué es | De dónde sale |
|---|---|---|
| `agent.md` | Las instrucciones del agente (prompt versión 8) | `agente/prompt.md` |
| `SKILL.md` | El conocimiento del proceso, como *Agent Skill* | `knowledge/registro-proveedor.md` |
| Servidor MCP | Las herramientas | `scripts/servidor_mcp.py` (el mismo registro del chat) |

## Conectar el servidor MCP

Desde la carpeta del proyecto (con `uv sync` hecho):

```
claude mcp add registro-proveedor -- uv run python scripts/servidor_mcp.py
```

En Claude Desktop, en su archivo de configuración de servidores MCP:

```json
{
  "mcpServers": {
    "registro-proveedor": {
      "command": "uv",
      "args": ["run", "--directory", "<carpeta del proyecto>", "python", "scripts/servidor_mcp.py"]
    }
  }
}
```

No necesita la clave de Anthropic: el modelo lo pone el cliente. Lee `datos/`, escribe
en `out/` y usa la fecha real.

## Herramientas que publica

- `proveedor_armar_paquete`
- `proveedor_generar_formulario`
- `proveedor_leer_solicitud`
- `proveedor_listar_casos`
- `proveedor_mapear_campos`

**No publica** `proveedor_confirmar_campo` ni `proveedor_registrar_envio`: requieren la
aprobación de la analista con el botón **Aprobar**, que solo existe en la aplicación. Por
MCP, esa decisión quedaría en manos del programa cliente (principio 3). Por eso, en
`agent.md`, lo que dice sobre aprobar aplica solo dentro de la aplicación.

## Garantías que se mantienen

- Nunca se inventa un valor: lo que no está en el maestro queda faltante.
- Los datos sensibles (cuenta bancaria, identificación) salen enmascarados.
- Cada llamada queda en `out/log.jsonl`.
- Si un resultado trae texto con forma de orden, llega con un aviso: es un dato del
  cliente, no una instrucción.
