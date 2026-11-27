"""Regenera las versiones HTML de los documentos, para leerlos mejor en el navegador.

Uso:
    uv run python scripts/regenerar_html.py

Cada HTML lleva el Markdown incrustado en `const md = "...";` y lo dibuja con `marked`,
con un índice a la izquierda. Se usa la plantilla de `SOLUCION.html`: así los cuatro se
ven igual. Hay que correrlo después de editar cualquiera de los `.md` de la lista.

En la versión HTML, los enlaces a los otros documentos (`SOLUCION.md`, `modulo/LEEME.md`…)
se cambian por su `.html`, para pasar de uno a otro sin salir del navegador.
"""

import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PLANTILLA = RAIZ / "SOLUCION.html"

# (Markdown, HTML, título de la pestaña del navegador)
DOCUMENTOS = [
    ("SOLUCION.md", "SOLUCION.html", "Solución Registro Proveedor"),
    ("PLAN-agente-registro-proveedor.md", "PLAN-agente-registro-proveedor.html", None),
    ("README.md", "README.html", "Registro como Proveedor"),
    ("modulo/LEEME.md", "modulo/LEEME.html", "Instalar el MCP"),
]
# Los .md que tienen versión HTML: un enlace a ellos pasa a apuntar al .html.
CON_HTML = {Path(md).name: Path(html).name for md, html, _ in DOCUMENTOS}

_MD = re.compile(r'const md = ".*?";', re.DOTALL)
_TITULO = re.compile(r"<title>.*?</title>", re.DOTALL)


def enlaces_a_html(texto: str) -> str:
    """ "(modulo/LEEME.md)" → "(modulo/LEEME.html)", solo en los enlaces de Markdown."""

    def cambiar(encontrado: re.Match[str]) -> str:
        ruta = encontrado.group(1)
        nombre = Path(ruta).name
        if nombre not in CON_HTML:
            return encontrado.group(0)
        return f"]({ruta[: len(ruta) - len(nombre)]}{CON_HTML[nombre]})"

    return re.sub(r"\]\(([^)\s]+\.md)\)", cambiar, texto)


def regenerar(md: str, html: str, titulo: str | None) -> None:
    plantilla = PLANTILLA.read_text(encoding="utf-8")
    destino = RAIZ / html
    base = destino.read_text(encoding="utf-8") if destino.exists() else plantilla
    texto = enlaces_a_html((RAIZ / md).read_text(encoding="utf-8"))
    nuevo = "const md = " + json.dumps(texto, ensure_ascii=False).replace("</", "<\\/") + ";"
    resultado, cambios = _MD.subn(lambda _: nuevo, base, count=1)
    if cambios != 1:
        raise SystemExit(f"{html}: no se encontró «const md = ...;»")
    if titulo is not None:
        resultado = _TITULO.sub(f"<title>{titulo}</title>", resultado, count=1)
    destino.write_text(resultado, encoding="utf-8", newline="")
    print(f"escrito: {html}")


if __name__ == "__main__":
    for md, html, titulo in DOCUMENTOS:
        regenerar(md, html, titulo)
