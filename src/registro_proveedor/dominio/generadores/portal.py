"""Valores para portal: `valores-portal.md`, una tabla "campo → valor" lista para copiar.

El formato portal no se automatiza en el MVP (HU-3): la analista entra al portal del
cliente con sus credenciales y copia cada valor. El texto vive en una plantilla de
Jinja2 (`plantillas/valores-portal.md.j2`), no en el código.

Este archivo SÍ lleva los valores completos, incluida la cuenta bancaria: el portal
los pide. Vive en `out/`, que nunca se le envía al modelo de lenguaje.
"""

from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined

from registro_proveedor.dominio.casos import CasoLeido
from registro_proveedor.dominio.generadores.comun import (
    TEXTO_ESTADO,
    FormularioGenerado,
    Marca,
    escribir_atomico,
    escrituras,
    resumen,
)
from registro_proveedor.dominio.mapeo import Mapeo

ARCHIVO_PORTAL = "valores-portal.md"


def celda_md(texto: str) -> str:
    """Texto seguro dentro de una celda de tabla Markdown.

    Un "|" cortaría la columna y un salto de línea cortaría la fila, así que se
    reemplazan. Es un "filtro" de Jinja2: en la plantilla se usa como `valor | celda_md`.
    """
    return texto.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def entorno() -> Environment:
    """El entorno de Jinja2 que lee las plantillas del paquete `registro_proveedor/plantillas/`.

    - `StrictUndefined`: si la plantilla usa una variable que no se le pasó, falla en
      vez de escribir un texto vacío sin que nadie lo note.
    - `autoescape=False`: el resultado es Markdown, no HTML.
    - `keep_trailing_newline`: el archivo termina con un salto de línea, como debe ser.
    """
    env = Environment(
        loader=PackageLoader("registro_proveedor", "plantillas"),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    env.filters["celda_md"] = celda_md
    return env


def generar_portal(mapeo: Mapeo, caso: CasoLeido, carpeta: Path) -> FormularioGenerado:
    """Escribe `valores-portal.md` en la carpeta del caso y devuelve el resumen."""
    lista = escrituras(mapeo)
    texto = (
        entorno()
        .get_template(f"{ARCHIVO_PORTAL}.j2")
        .render(
            cliente=caso.cliente,
            caso=caso.caso,
            generado_en=mapeo.generado_en.date().isoformat(),
            version_maestro=mapeo.version_maestro or "sin versión",
            escrituras=lista,
            estados=TEXTO_ESTADO,
            pendientes=[e.etiqueta for e in lista if e.marca is Marca.PENDIENTE],
            faltantes=[e.etiqueta for e in lista if e.marca is Marca.FALTANTE],
        )
    )
    destino = carpeta / ARCHIVO_PORTAL
    escribir_atomico(destino, lambda ruta: ruta.write_text(texto, encoding="utf-8"))
    return resumen(destino, lista)
