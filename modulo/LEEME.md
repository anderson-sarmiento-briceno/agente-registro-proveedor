# Módulo reutilizable · Registro como Proveedor

Estas piezas son **las mismas** que usa la aplicación (no son copias aparte): se generan
con `uv run python scripts/exportar_modulo.py` y una prueba revisa que estén al día.

| Archivo | Qué es | De dónde sale |
|---|---|---|
| `agent.md` | Las instrucciones del agente (prompt versión 8) | `agente/prompt.md` |
| `SKILL.md` | El conocimiento del proceso, como *Agent Skill* | `knowledge/registro-proveedor.md` |
| Servidor MCP | Las herramientas | `scripts/servidor_mcp.py` (el mismo registro del chat) |

## La forma más fácil: conectarlo en línea (sin instalar nada)

El servidor MCP también está publicado en internet, junto a la demo. Solo hay que
agregarlo como **conector personalizado** en Claude (la aplicación de escritorio o
claude.ai):

1. Abra **Configuración (Settings)** → **Conectores (Connectors)**.
2. Pulse **Agregar conector personalizado (Add custom connector)**.
3. Escriba un nombre (por ejemplo, `Registro como Proveedor`) y esta URL:

   ```
   https://agente-registro-proveedor-yu72.onrender.com/mcp
   ```

4. Pulse **Agregar (Add)**. En un chat nuevo, actívelo en el menú de herramientas o
   conectores y pruebe las frases del punto 5 de más abajo.

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
    <https://github.com/anderson-sarmiento-briceno/agente-registro-proveedor>, pulse el botón verde **Code** → **Download ZIP** y
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

(Con Git, en cambio: `git clone https://github.com/anderson-sarmiento-briceno/agente-registro-proveedor.git`, después
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

Por ejemplo, en Windows: `C:\Users\<usuario>\.local\bin\uv.exe` y
`C:\Users\<usuario>\Documents\agente-registro-proveedor`.

### 4A. Conectarlo a Claude Desktop

1. Abra Claude Desktop → **Configuración (Settings)** → **Developer (Desarrollador)** →
   **Edit Config**. Se abre el archivo `claude_desktop_config.json`:
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
2. Agregue este bloque con **sus** dos rutas. En Windows, cada `\` de la ruta se escribe
   doble (`\\`), porque así lo pide el formato JSON:

   ```json
   {
     "mcpServers": {
       "registro-proveedor": {
         "command": "C:\\Users\\<usuario>\\.local\\bin\\uv.exe",
         "args": [
           "run",
           "--directory",
           "C:\\Users\\<usuario>\\Documents\\agente-registro-proveedor",
           "python",
           "scripts/servidor_mcp.py"
         ]
       }
     }
   }
   ```

   En macOS sería, por ejemplo, `"command": "/Users/<usuario>/.local/bin/uv"` y la carpeta
   `"/Users/<usuario>/agente-registro-proveedor"`. Si el archivo ya tiene otros servidores
   dentro de `"mcpServers"`, agregue solo la parte de `"registro-proveedor"`, separada por una coma.
3. **Cierre Claude Desktop del todo** (en Windows, también desde el ícono junto al reloj:
   clic derecho → Quit) y vuelva a abrirlo.
4. En el chat, en el menú de herramientas o conectores, debe aparecer **registro-proveedor** con
   sus 5 herramientas.

### 4B. O conectarlo a Claude Code

Dentro de la carpeta del proyecto:

```
claude mcp add registro-proveedor -- uv run python scripts/servidor_mcp.py
```

### 5. Probarlo

| Escriba en el chat | Qué debe pasar |
|---|---|
| «Usa registro-proveedor y dime qué casos hay» | Llama a `proveedor_listar_casos`: 4 casos |
| «Prepara el caso de Colombia» | Leer → mapear → generar → armar: **listo para firma** |
| «¿Qué le falta al caso de Honduras?» | Parafiscales vencidos y el RTN por confirmar |
| «Confirma el RUC de Panamá» | Responde que **no está disponible por MCP** (va en la app) |

El programa le pedirá permiso antes de usar cada herramienta: es normal. Lo que genera
queda en la carpeta `out/` del proyecto (formularios, paquetes y `out/log.jsonl`).

### 6. Si algo no funciona

- **No aparece el servidor:** revise que el JSON no tenga errores (comas, comillas, las
  `\\` dobles en Windows) y que cerró Claude Desktop del todo.
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
