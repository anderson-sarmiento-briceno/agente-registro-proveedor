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
URL_REPOSITORIO = "https://github.com/anderson-sarmiento-briceno/agente-registro-proveedor"
URL_MCP_EN_LINEA = "https://agente-registro-proveedor-yu72.onrender.com/mcp"
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

## La forma más fácil: conectarlo en línea (sin instalar nada)

El servidor MCP también está publicado en internet, junto a la demo. Solo hay que
agregarlo como **conector personalizado** en Claude (la aplicación de escritorio o
claude.ai):

1. Abra **Configuración** → **Plugins** (en otras versiones se llama **Conectores**).
2. Pulse el botón negro **Agregar ⌄** (arriba a la derecha) → **Agregar conector
   personalizado**.
3. Escriba un nombre (por ejemplo, `Registro como Proveedor`) y esta URL:

   ```
   {URL_MCP_EN_LINEA}
   ```

4. En **Autenticación**, deje **«Sin inicio de sesión»** (Claude lo marca solo como
   «Detectado»). El aviso amarillo de que cualquiera con la URL puede usarlo es normal:
   es una demostración abierta. No agregue encabezados ni cambie «Avanzada».
5. Pulse **Agregar**. Debe aparecer en **Tus plugins**.
6. En un chat nuevo, en el botón de herramientas (junto a donde se escribe), revise que
   **Registro como Proveedor** esté activado, y pruebe las frases del punto 5 de más
   abajo. Claude pide permiso antes de usar cada herramienta: acéptelo.

Para tener en cuenta:
- Los conectores personalizados dependen del plan de Claude de cada persona; si no
  aparece la opción, use la instalación en su computador (abajo).
- Es una demostración pública, con datos de una empresa ficticia. No gasta ninguna clave
  de Anthropic: el modelo lo pone la cuenta de Claude de quien se conecta.
- La primera conexión puede tardar cerca de un minuto: el servidor gratuito se apaga
  cuando nadie lo usa y tiene que volver a encender.

## Instalarlo en su computador, paso a paso

Solo hace falta el repositorio de GitHub. **No necesita la clave de Anthropic:** el modelo
lo pone el programa que se conecta (Claude Desktop o Claude Code, con su propia cuenta).

### 1. Requisitos (una sola vez)

- **El proyecto**, de una de estas dos formas:
  - **Sin Git (lo más simple):** en la página del repositorio,
    <{URL_REPOSITORIO}>, pulse el botón verde **Code** → **Download ZIP** y
    descomprímalo donde quiera (por ejemplo, en Documentos).
  - **Con Git** (<https://git-scm.com/downloads>), en el paso 2.
- **uv**, que instala Python y las librerías del proyecto
  (<https://docs.astral.sh/uv/getting-started/installation/>):
  - Windows (en PowerShell):

    ```
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

  - macOS o Linux (en la Terminal):

    ```
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

  Cierre y vuelva a abrir la terminal después de instalarlo.

### 2. Instalar las librerías

Abra PowerShell (Windows) o la Terminal (macOS/Linux) **dentro de la carpeta del
proyecto**. Si descargó el ZIP, la carpeta se llama `agente-registro-proveedor-main`. En
Windows, se puede abrir con clic derecho sobre la carpeta → «Abrir en Terminal». Luego:

```
uv sync
```

(Con Git, en cambio: `git clone {URL_REPOSITORIO}.git`, después
`cd agente-registro-proveedor` y `uv sync`.)

`uv sync` descarga Python 3.13 si hace falta y todas las librerías. Para comprobar que
quedó bien (no necesita clave ni internet):

```
uv run python scripts/demo.py
```

Debe terminar con «4 casos procesados · 1 listo para firma · 3 no listos · 0 con error».

### 3. Anotar dos rutas

Claude Desktop necesita las rutas **completas**:

| Qué | Cómo obtenerla |
|---|---|
| La de `uv` | Windows: `where.exe uv` · macOS/Linux: `which uv` |
| La del proyecto | Windows: `cd` (dentro de la carpeta) · macOS/Linux: `pwd` |

Por ejemplo, en Windows: `C:\\Users\\<usuario>\\.local\\bin\\uv.exe` y
`C:\\Users\\<usuario>\\Documents\\agente-registro-proveedor`.

### 4A. Conectarlo a Claude Desktop

1. Abra Claude Desktop → **Configuración (Settings)** → **Developer (Desarrollador)** →
   **Edit Config**. Se abre el archivo `claude_desktop_config.json`:
   - Windows: `%APPDATA%\\Claude\\claude_desktop_config.json`
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
2. Agregue este bloque con **sus** dos rutas. En Windows, cada `\\` de la ruta se escribe
   doble (`\\\\`), porque así lo pide el formato JSON:

   ```json
   {{
     "mcpServers": {{
       "{NOMBRE}": {{
         "command": "C:\\\\Users\\\\<usuario>\\\\.local\\\\bin\\\\uv.exe",
         "args": [
           "run",
           "--directory",
           "C:\\\\Users\\\\<usuario>\\\\Documents\\\\agente-registro-proveedor",
           "python",
           "scripts/servidor_mcp.py"
         ]
       }}
     }}
   }}
   ```

   En macOS sería, por ejemplo, `"command": "/Users/<usuario>/.local/bin/uv"` y la carpeta
   `"/Users/<usuario>/agente-registro-proveedor"`. Si el archivo ya tiene otros servidores
   dentro de `"mcpServers"`, agregue solo la parte de `"{NOMBRE}"`, separada por una coma.
3. **Cierre Claude Desktop del todo** (en Windows, también desde el ícono junto al reloj:
   clic derecho → Quit) y vuelva a abrirlo.
4. En el chat, en el menú de herramientas o conectores, debe aparecer **{NOMBRE}** con
   sus 5 herramientas.

### 4B. O conectarlo a Claude Code

Dentro de la carpeta del proyecto:

```
claude mcp add {NOMBRE} -- uv run python scripts/servidor_mcp.py
```

### 5. Probarlo

| Escriba en el chat | Qué debe pasar |
|---|---|
| «Usa {NOMBRE} y dime qué casos hay» | Llama a `proveedor_listar_casos`: 4 casos |
| «Prepara el caso de Colombia» | Leer → mapear → generar → armar: **listo para firma** |
| «¿Qué le falta al caso de Honduras?» | Parafiscales vencidos y el RTN por confirmar |
| «Confirma el RUC de Panamá» | Responde que **no está disponible por MCP** (va en la app) |

El programa le pedirá permiso antes de usar cada herramienta: es normal. Lo que genera
queda en la carpeta `out/` del proyecto (formularios, paquetes y `out/log.jsonl`).

### 6. Si algo no funciona

- **No aparece el servidor:** revise que el JSON no tenga errores (comas, comillas, las
  `\\\\` dobles en Windows) y que cerró Claude Desktop del todo.
- **Error al arrancar:** en **Settings → Developer**, junto al servidor, está su log. El
  error más común es una ruta de `uv` o de la carpeta mal escrita.
- **Fechas raras:** si existe un archivo `.env` con `FECHA_EJECUCION`, el servidor usa esa
  fecha. Déjela vacía para usar la de hoy.

### 7. Usar también las instrucciones y el conocimiento

- `agent.md` son las instrucciones del agente: se pueden usar como *subagente* en Claude
  Code (copiándolo a `.claude/agents/`) o como instrucciones de otro agente.
- `SKILL.md` es el conocimiento del proceso, en el formato de las *Agent Skills*: se
  puede cargar como skill en las plataformas que lo admiten.

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
