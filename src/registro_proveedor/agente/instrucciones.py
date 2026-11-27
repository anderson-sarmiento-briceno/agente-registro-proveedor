"""Las instrucciones de sistema del agente: el prompt (comportamiento) + el conocimiento.

¿Qué es el "sistema"?
    Es el texto fijo que el modelo recibe en CADA llamada, antes de la conversación.
    Le dice quién es, en qué orden pedir las herramientas, qué tiene prohibido y cómo
    resumir. No se programa en Python: se escribe en dos archivos Markdown, para poder
    ajustarlo sin tocar el código (sección 9.5 del plan):

        agente/prompt.md                 → COMPORTAMIENTO (rol, flujo, prohibiciones,
                                           formato del resumen, correo = datos)
        knowledge/registro-proveedor.md  → CONOCIMIENTO del proceso (países, soportes,
                                           estados), para que el modelo pueda explicar

¿Por qué el conocimiento va dentro del sistema y no en una herramienta? (D41)
    Es corto, y el sistema va en la caché del proveedor (CA7): desde la segunda llamada
    cuesta una décima parte. Con una herramienta, el modelo tendría que acordarse de
    consultarlo y gastaría una llamada más. Si un día crece mucho, se pasa a una
    herramienta de búsqueda.

Versión y huella (HU-7):
    `prompt.md` empieza con un encabezado `version: N`, que se sube a mano cuando el
    comportamiento cambia. La `huella` es un resumen (SHA-256) del texto final: cambia
    con CUALQUIER edición, también del conocimiento. Las dos irán al log de cada sesión
    (Paso 12), para saber con qué instrucciones se trabajó.

Este módulo solo lee: no llama al modelo.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from registro_proveedor.config import RAIZ_PROYECTO
from registro_proveedor.dominio.lectura import ErrorDeDatos

RUTA_PROMPT = RAIZ_PROYECTO / "agente" / "prompt.md"
RUTA_CONOCIMIENTO = RAIZ_PROYECTO / "knowledge" / "registro-proveedor.md"

# El encabezado va entre dos líneas "---" al comienzo del archivo (como en muchos
# sistemas de documentación). `\A` = el comienzo del texto; `.*?` = lo mínimo posible.
_ENCABEZADO = re.compile(r"\A---\n(?P<campos>.*?)\n---\n", re.DOTALL)

# Lo que separa el comportamiento del conocimiento en el texto final.
SEPARADOR = "\n\n---\n\n"


@dataclass(frozen=True)
class InstruccionesSistema:
    """El texto que se le da al modelo como sistema, con su versión y su huella."""

    texto: str
    version: str
    huella: str  # 12 primeros caracteres del SHA-256 del texto


def cargar_instrucciones(
    ruta_prompt: Path = RUTA_PROMPT, ruta_conocimiento: Path = RUTA_CONOCIMIENTO
) -> InstruccionesSistema:
    """Lee el prompt y el conocimiento y los junta. Lanza `ErrorDeDatos` si algo falta.

    Las rutas se pueden cambiar para las pruebas.
    """
    partes = leer_partes(ruta_prompt, ruta_conocimiento)
    texto = partes.comportamiento + SEPARADOR + partes.conocimiento + "\n"
    huella = hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12]
    return InstruccionesSistema(texto=texto, version=partes.version, huella=huella)


@dataclass(frozen=True)
class PartesDeInstrucciones:
    """El prompt y el conocimiento por separado, ya limpios (sin encabezado ni espacios)."""

    version: str
    comportamiento: str  # agente/prompt.md sin su encabezado
    conocimiento: str  # knowledge/registro-proveedor.md


def leer_partes(
    ruta_prompt: Path = RUTA_PROMPT, ruta_conocimiento: Path = RUTA_CONOCIMIENTO
) -> PartesDeInstrucciones:
    """Las dos partes por separado. La usan el chat (juntas) y el Paso 20 (`agent.md` y
    `SKILL.md`): así las dos salidas vienen SIEMPRE del mismo texto."""
    version, comportamiento = _separar_encabezado(ruta_prompt, _leer(ruta_prompt))
    return PartesDeInstrucciones(
        version=version,
        comportamiento=comportamiento.strip(),
        conocimiento=_leer(ruta_conocimiento).strip(),
    )


def _leer(ruta: Path) -> str:
    """El archivo como texto, con saltos de línea `\\n`.

    En Windows, git puede guardar los archivos con saltos `\\r\\n`. Se normalizan para
    que el texto (y su huella) sea el mismo en cualquier máquina. `utf-8-sig` ignora la
    marca BOM que agregan algunos editores al comienzo del archivo.
    """
    try:
        texto = ruta.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ErrorDeDatos(ruta, ["no existe el archivo de instrucciones del agente"]) from None
    texto = texto.replace("\r\n", "\n")
    if not texto.strip():
        raise ErrorDeDatos(ruta, ["el archivo de instrucciones está vacío"])
    return texto


def _separar_encabezado(ruta: Path, texto: str) -> tuple[str, str]:
    """(versión, resto del texto). El encabezado no se le envía al modelo."""
    encontrado = _ENCABEZADO.match(texto)
    if encontrado is None:
        raise ErrorDeDatos(
            ruta, ["falta el encabezado con la versión: el archivo debe empezar con «---»"]
        )
    try:
        campos = yaml.safe_load(encontrado["campos"])
    except yaml.YAMLError:
        campos = None
    version = campos.get("version") if isinstance(campos, dict) else None
    # Se acepta `version: 1` (número) o `version: "1.2"` (texto); vacío o booleano, no.
    if isinstance(version, bool) or not isinstance(version, int | str) or not str(version):
        raise ErrorDeDatos(ruta, ["el encabezado debe tener «version: <número>»"])
    return str(version), texto[encontrado.end() :]
