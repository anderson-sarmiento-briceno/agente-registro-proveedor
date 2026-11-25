"""Formulario PDF: título con el cliente y los campos en el mismo orden de la plantilla.

Se genera un PDF nuevo con fpdf2, como una tabla de dos columnas: etiqueta y valor.
Los obligatorios llevan "*". Los faltantes y los pendientes quedan vacíos y
resaltados (amarillo y naranja), igual que en el Excel.

Pendiente (anotado en SOLUCION.md): si el cliente envía un PDF con campos
rellenables (AcroForm), lo correcto es rellenar ESE archivo con pypdf. Ningún caso
de ejemplo trae uno, así que no se implementa sin poder probarlo.

Sobre las letras: las fuentes incluidas en fpdf2 (Helvetica) solo tienen los
caracteres "latin-1", que cubren el español (á, é, ñ, ¿, ...). Un carácter fuera de
ese grupo se reemplaza por "?" en lugar de romper la generación.
"""

from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

from registro_proveedor.dominio.casos import CasoLeido
from registro_proveedor.dominio.generadores.comun import (
    COLOR_FALTANTE,
    COLOR_PENDIENTE,
    FormularioGenerado,
    Marca,
    escribir_atomico,
    escrituras,
    resumen,
)
from registro_proveedor.dominio.mapeo import Mapeo

ARCHIVO_PDF = "formulario.pdf"
AUTOR = "Agente Registro como Proveedor"


def _rgb(hexadecimal: str) -> tuple[int, int, int]:
    """Convierte un color hexadecimal en sus tres números: FFF2CC → (255, 242, 204)."""
    return (int(hexadecimal[0:2], 16), int(hexadecimal[2:4], 16), int(hexadecimal[4:6], 16))


ESTILOS = {
    Marca.FALTANTE: FontFace(fill_color=_rgb(COLOR_FALTANTE)),
    Marca.PENDIENTE: FontFace(fill_color=_rgb(COLOR_PENDIENTE)),
}
NEGRITA = FontFace(emphasis="BOLD")


def latin1(texto: str) -> str:
    """El texto con los caracteres que la fuente no tiene reemplazados por "?"."""
    return texto.encode("latin-1", "replace").decode("latin-1")


def generar_pdf(mapeo: Mapeo, caso: CasoLeido, carpeta: Path) -> FormularioGenerado:
    """Escribe `formulario.pdf` en la carpeta del caso y devuelve el resumen."""
    lista = escrituras(mapeo)
    pdf = FPDF(format="A4")
    # Fecha interna = fecha del mapeo, para que el contenido sea reproducible.
    pdf.set_creation_date(mapeo.generado_en)
    pdf.set_author(AUTOR)
    pdf.set_title(latin1(f"Registro de proveedor - {caso.cliente}"))
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 9, latin1("Formulario de registro de proveedor"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, latin1(f"Cliente: {caso.cliente}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    with pdf.table(col_widths=(40, 60), first_row_as_headings=False, line_height=7) as tabla:
        for e in lista:
            fila = tabla.row()
            fila.cell(latin1(e.etiqueta + (" *" if e.obligatorio else "")), style=NEGRITA)
            fila.cell(latin1(e.valor or ""), style=ESTILOS.get(e.marca))

    pdf.ln(4)
    pdf.set_font("Helvetica", "", 8)
    pdf.multi_cell(
        0,
        4,
        latin1(
            "* Campo obligatorio. Celdas amarillas: dato que falta en el repositorio maestro. "
            "Celdas naranjas: dato pendiente de confirmación."
        ),
    )
    destino = carpeta / ARCHIVO_PDF
    escribir_atomico(destino, lambda ruta: pdf.output(str(ruta)))
    return resumen(destino, lista)
