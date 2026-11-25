"""El entorno de Jinja2 que usan todas las plantillas de texto del proyecto.

Las plantillas (`registro_proveedor/plantillas/*.j2`) guardan el TEXTO de negocio:
los valores para el portal (Paso 7), el checklist y el borrador del correo (Paso 8).
Así el texto no se mezcla con el código Python, y cambiar una frase no obliga a
tocar la lógica.
"""

from jinja2 import Environment, PackageLoader, StrictUndefined


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
    - `autoescape=False`: los resultados son Markdown, no HTML.
    - `keep_trailing_newline`: el archivo termina con un salto de línea, como debe ser.
    - `trim_blocks` y `lstrip_blocks`: una línea que solo tiene una etiqueta de lógica
      (un "si" o un ciclo) desaparece entera del resultado, sin dejar una línea en blanco
      suelta. Así las plantillas se escriben tal como se leen.
    """
    env = Environment(
        loader=PackageLoader("registro_proveedor", "plantillas"),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["celda_md"] = celda_md
    return env


def renderizar(plantilla: str, **variables: object) -> str:
    """El texto de una plantilla con sus variables: `renderizar("checklist.md.j2", ...)`."""
    return entorno().get_template(plantilla).render(**variables)
