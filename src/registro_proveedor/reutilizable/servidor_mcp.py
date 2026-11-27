"""Las herramientas del agente como servidor MCP (Paso 20).

¿Qué es MCP?
    El "Model Context Protocol" es un estándar para que un asistente de IA use
    herramientas externas, como un enchufe universal. Con este servidor, cualquier
    plataforma que hable MCP (Claude Desktop, Claude Code, la plataforma de agentes de
    una empresa) puede usar las herramientas del registro como proveedor sin pasar por
    nuestra página.

Sin copias (el "hecho cuando" del paso):
    El servidor NO define herramientas propias. Lee el MISMO `registro` del chat:
        - la lista (nombre, descripción y argumentos) sale de `definiciones_desde_registro`,
          la misma función que arma lo que ve el modelo en el chat;
        - cada llamada pasa por `registro.ejecutar`, que valida los argumentos, ejecuta,
          deja la línea en `log.jsonl` y nunca lanza;
        - la respuesta sale de `Resultado.a_json()`: con lo sensible ENMASCARADO.
    Si mañana se agrega una herramienta al registro, aparece sola en el MCP.

Qué NO se expone (decisión de Anderson, opción A):
    Las herramientas que requieren aprobación (`proveedor_confirmar_campo` y
    `proveedor_registrar_envio`). En la aplicación solo se ejecutan cuando la analista
    pulsa Aprobar en NUESTRO servidor (principio 3). Por MCP no existe ese botón: la
    aprobación quedaría en manos del programa cliente. Se hacen en la aplicación.

Principio 5 (contenido externo = dato): si un resultado trae texto con forma de orden,
se le antepone el mismo aviso que en el chat, para el modelo que lo reciba.

Cómo se usa (corre en el computador de quien lo usa, por stdio):
    uv run python scripts/servidor_mcp.py
    claude mcp add registro-proveedor -- uv run python scripts/servidor_mcp.py
"""

from collections.abc import Callable
from typing import Any

import mcp.types as tipos
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from registro_proveedor.agente.ciclo import AVISO_INSTRUCCION
from registro_proveedor.agente.guardarrailes import detectar_instrucciones
from registro_proveedor.agente.llm.adaptador import definiciones_desde_registro
from registro_proveedor.config import Configuracion
from registro_proveedor.herramientas.base import Contexto, Registro
from registro_proveedor.herramientas.proveedor import registro as registro_real

NOMBRE = "registro-proveedor"

# Las que solo leen: el cliente puede llamarlas sin miedo (las demás escriben en out/,
# pero siempre igual: llamarlas dos veces da lo mismo).
SOLO_LECTURA = frozenset({"proveedor_listar_casos", "proveedor_leer_solicitud"})

INSTRUCCIONES = (
    "Herramientas para preparar el registro de la empresa como proveedor ante un cliente: "
    "listar los casos, leer la solicitud, mapear los campos al maestro de la empresa, "
    "generar el formulario y armar el paquete para firma (en ese orden). Nunca inventan "
    "un valor: lo que no está en el maestro queda faltante. Los datos sensibles llegan "
    "enmascarados. Confirmar un campo y registrar el envío requieren la aprobación de la "
    "analista y se hacen en la aplicación, no por aquí."
)

# El contexto de MCP de cada solicitud. `Any` porque el SDK lo tipa con el resultado del
# "lifespan" del servidor, que aquí no se usa (no guardamos nada entre solicitudes).
Contexto_MCP = ServerRequestContext[Any]


def expuestas(registro: Registro) -> list[str]:
    """Los nombres de las herramientas que se publican por MCP (sin las de aprobación)."""
    return [h.nombre for h in registro.listar() if not h.requiere_confirmacion]


def crear_servidor(
    crear_contexto: Callable[[], Contexto], registro: Registro = registro_real
) -> Server[Any]:
    """El servidor MCP sobre el registro dado. `crear_contexto` da datos/, out/ y la fecha.

    Las pruebas pasan un contexto con un `out/` temporal; el script, el real.
    """
    nombres = set(expuestas(registro))
    definiciones = [d for d in definiciones_desde_registro(registro) if d.nombre in nombres]

    async def listar(_ctx: Contexto_MCP, _params: object) -> tipos.ListToolsResult:
        return tipos.ListToolsResult(
            tools=[
                tipos.Tool(
                    name=d.nombre,
                    description=d.descripcion,
                    input_schema=dict(d.parametros),
                    annotations=tipos.ToolAnnotations(
                        read_only_hint=d.nombre in SOLO_LECTURA,
                        destructive_hint=False,
                        idempotent_hint=True,
                        open_world_hint=False,
                    ),
                )
                for d in definiciones
            ]
        )

    async def llamar(
        _ctx: Contexto_MCP, params: tipos.CallToolRequestParams
    ) -> tipos.CallToolResult:
        if params.name not in nombres:
            return _error(
                f"la herramienta «{params.name}» no está disponible por MCP. Confirmar un "
                "campo y registrar el envío requieren la aprobación de la analista: se "
                "hacen en la aplicación."
                if registro.obtener(params.name) is not None
                else f"no existe la herramienta «{params.name}»"
            )
        resultado = registro.ejecutar(params.name, dict(params.arguments or {}), crear_contexto())
        return _respuesta(resultado.a_json(), resultado.error, ok=resultado.ok)

    return Server(
        NOMBRE,
        version="1",
        instructions=INSTRUCCIONES,
        on_list_tools=listar,
        on_call_tool=llamar,
    )


def _respuesta(contenido: str, error: str | None, *, ok: bool) -> tipos.CallToolResult:
    """El resultado (ya enmascarado) como texto; con un aviso si trae algo con forma de orden."""
    tipos_sospechosos = (
        detectar_instrucciones(contenido)
        if ok
        else detectar_instrucciones(error or "", incluir_herramientas=False)
    )
    if tipos_sospechosos:
        contenido = f"{AVISO_INSTRUCCION} ({', '.join(tipos_sospechosos)})\n{contenido}"
    return tipos.CallToolResult(
        content=[tipos.TextContent(type="text", text=contenido)], is_error=not ok
    )


def _error(mensaje: str) -> tipos.CallToolResult:
    return tipos.CallToolResult(
        content=[tipos.TextContent(type="text", text=mensaje)], is_error=True
    )


async def correr(config: Configuracion) -> None:
    """Atiende a un cliente MCP por la entrada y la salida estándar (stdio)."""

    def contexto() -> Contexto:
        return Contexto.desde_configuracion(config, sesion_id="mcp")

    servidor = crear_servidor(contexto)
    async with stdio_server() as (lectura, escritura):
        await servidor.run(lectura, escritura, servidor.create_initialization_options())
