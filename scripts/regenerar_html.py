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

# Los diagramas Mermaid (```mermaid) que GitHub dibuja solo: aquí se dibujan con la
# librería mermaid, cargada SOLO si la página tiene alguno. Se agrega una sola vez,
# justo después de la línea que convierte el Markdown en HTML.
_TRAS_MARKED = (
    'contenido.innerHTML = window.marked ? marked.parse(md) : "<pre>" + '
    'md.replace(/[&<]/g, c => c === "&" ? "&amp;" : "&lt;") + "</pre>";'
)
_MERMAID = """
  contenido.querySelectorAll("pre code.language-mermaid").forEach((codigo) => {
    const figura = document.createElement("div");
    figura.className = "mermaid";
    figura.textContent = codigo.textContent;
    codigo.parentElement.replaceWith(figura);
  });
  if (contenido.querySelector(".mermaid")) {
    import("https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.esm.min.mjs").then((m) => {
      const oscuro = matchMedia("(prefers-color-scheme: dark)").matches;
      m.default.initialize({ startOnLoad: false, theme: oscuro ? "dark" : "default" });
      m.default.run({ querySelector: ".mermaid" });
    });
  }"""


def con_mermaid(html: str) -> str:
    """El HTML con el paso que dibuja los diagramas (si todavía no lo tiene)."""
    if "language-mermaid" in html or _TRAS_MARKED not in html:
        return html
    return html.replace(_TRAS_MARKED, _TRAS_MARKED + _MERMAID, 1)


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
    destino.write_text(con_mermaid(resultado), encoding="utf-8", newline="")
    print(f"escrito: {html}")


if __name__ == "__main__":
    for md, html, titulo in DOCUMENTOS:
        regenerar(md, html, titulo)
