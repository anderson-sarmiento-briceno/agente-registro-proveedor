"""Exporta el prompt como `agent.md` y el conocimiento como `SKILL.md` (Paso 20).

¿Para qué?
    Otras plataformas de agentes no leen nuestro `agente/prompt.md` ni
    `knowledge/registro-proveedor.md`: esperan sus propios formatos.
        - `agent.md`: las instrucciones del agente, con un encabezado (nombre, descripción
          y versión), como los "subagentes" de Claude Code.
        - `SKILL.md`: el conocimiento del proceso como una "Agent Skill": un encabezado
          con nombre y descripción (cuándo usarla) y después el contenido.
    Más un `LEEME.md` que explica cómo conectar el servidor MCP y usar las dos piezas.

¿Cómo se evita que diverjan? (el "hecho cuando" del paso)
    El CUERPO de cada archivo es exactamente el texto original (`leer_partes`, la misma
    función que usa el chat): solo se le agrega el encabezado. Y una prueba compara la
    carpeta `modulo/` con lo que produciría el exportador ahora: si alguien cambia el
    prompt y no vuelve a exportar, la prueba (y el CI) fallan, igual que los golden.

    Para volver a exportar:  uv run python scripts/exportar_modulo.py
"""

from pathlib import Path

from registro_proveedor.agente.instrucciones import leer_partes
from registro_proveedor.config import RAIZ_PROYECTO
from registro_proveedor.herramientas.proveedor import registro
from registro_proveedor.reutilizable.servidor_mcp import NOMBRE, expuestas

CARPETA_MODULO = RAIZ_PROYECTO / "modulo"
AGENT_MD = "agent.md"
SKILL_MD = "SKILL.md"
LEEME_MD = "LEEME.md"

DESCRIPCION_AGENTE = (
    "Asistente que prepara el registro de la empresa como proveedor ante un cliente: "
    "lee la solicitud, llena el formulario con los datos del maestro de la empresa, arma "
    "el paquete para firma y dice qué falta. Nunca inventa un valor."
)
DESCRIPCION_SKILL = (
    "Conocimiento del proceso de registro como proveedor: identificador tributario por "
    "país, soportes que piden los clientes y sus estados (vigente, por vencer, vencido, "
    "ausente), estados de un campo y formatos de formulario. Úsala cuando haya que "
    "preparar o explicar un registro de proveedor."
)


def archivos_del_modulo() -> dict[str, str]:
    """El contenido de cada archivo de `modulo/`, armado desde los originales."""
    partes = leer_partes()
    agente = _con_encabezado(
        {"name": NOMBRE, "description": DESCRIPCION_AGENTE, "version": partes.version},
        partes.comportamiento,
    )
    skill = _con_encabezado({"name": NOMBRE, "description": DESCRIPCION_SKILL}, partes.conocimiento)
    return {AGENT_MD: agente, SKILL_MD: skill, LEEME_MD: _leeme(partes.version)}


def exportar(destino: Path = CARPETA_MODULO) -> list[Path]:
    """Escribe los archivos en `destino` (por defecto `modulo/`) y devuelve sus rutas."""
    destino.mkdir(parents=True, exist_ok=True)
    escritos: list[Path] = []
    for nombre, contenido in archivos_del_modulo().items():
        ruta = destino / nombre
        ruta.write_text(contenido, encoding="utf-8", newline="\n")
        escritos.append(ruta)
    return escritos


def desactualizados(destino: Path = CARPETA_MODULO) -> list[str]:
    """Los archivos de `destino` que no coinciden con los originales (vacío = al día)."""
    distintos: list[str] = []
    for nombre, esperado in archivos_del_modulo().items():
        ruta = destino / nombre
        actual = ruta.read_text(encoding="utf-8").replace("\r\n", "\n") if ruta.is_file() else None
        if actual != esperado:
            distintos.append(nombre)
    return distintos


def _con_encabezado(campos: dict[str, str], cuerpo: str) -> str:
    """El encabezado YAML entre «---» y después el cuerpo, tal cual."""
    lineas = ["---", *(f"{clave}: {_yaml(valor)}" for clave, valor in campos.items()), "---"]
    return "\n".join(lineas) + "\n\n" + cuerpo + "\n"


def _yaml(valor: str) -> str:
    """Un texto como valor YAML seguro: entre comillas dobles, escapando las comillas."""
    return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _leeme(version: str) -> str:
    herramientas = "\n".join(f"- `{nombre}`" for nombre in expuestas(registro))
    return f"""# Módulo reutilizable · Registro como Proveedor

Estas piezas son **las mismas** que usa la aplicación (no son copias aparte): se generan
con `uv run python scripts/exportar_modulo.py` y una prueba revisa que estén al día.

| Archivo | Qué es | De dónde sale |
|---|---|---|
| `agent.md` | Las instrucciones del agente (prompt versión {version}) | `agente/prompt.md` |
| `SKILL.md` | El conocimiento del proceso, como *Agent Skill* | `knowledge/registro-proveedor.md` |
| Servidor MCP | Las herramientas | `scripts/servidor_mcp.py` (el mismo registro del chat) |

## Conectar el servidor MCP

Desde la carpeta del proyecto (con `uv sync` hecho):

```
claude mcp add {NOMBRE} -- uv run python scripts/servidor_mcp.py
```

En Claude Desktop, en su archivo de configuración de servidores MCP:

```json
{{
  "mcpServers": {{
    "{NOMBRE}": {{
      "command": "uv",
      "args": ["run", "--directory", "<carpeta del proyecto>", "python", "scripts/servidor_mcp.py"]
    }}
  }}
}}
```

No necesita la clave de Anthropic: el modelo lo pone el cliente. Lee `datos/`, escribe
en `out/` y usa la fecha real.

## Herramientas que publica

{herramientas}

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
"""
