"""PDF sencillos para personas: títulos, párrafos, listas, tablas con colores y recuadros.

¿Para qué? (Paso 19, pedido de Anderson)
    El paquete del sistema usa formatos técnicos (`checklist.md`, `manifiesto.json`,
    soportes `.txt`), que necesita la auditoría pero que una persona sin conocimientos
    técnicos no sabe abrir. La DESCARGA de la demo los entrega en PDF, que se abre con
    doble clic en cualquier computador o celular. Los archivos del sistema no cambian.

Dos formas de escribir:
    - Con los métodos de `DocumentoPdf` (sección, párrafo, viñetas, tabla, recuadro),
      cuando los datos vienen estructurados (manifiesto.json, mapeo.json).
    - Con `desde_markdown`, para los textos que ya están en Markdown (el borrador del
      correo y la constancia): entiende títulos, párrafos, viñetas, citas y tablas.

Sobre las letras: igual que el formulario PDF, se usa Helvetica, que solo tiene los
caracteres "latin-1" (todo el español). Los emojis de los estados no existen en esa
fuente: se quitan, y el estado se muestra con PALABRAS y COLORES.
"""

import re
from collections.abc import Sequence

from fpdf import FPDF
from fpdf.fonts import FontFace

Color = tuple[int, int, int]
# Una celda de tabla: solo el texto, o el texto con un color de fondo.
Celda = str | tuple[str, Color | None]

VERDE: Color = (226, 239, 218)
AMARILLO: Color = (255, 242, 204)  # el mismo de los campos faltantes (COLOR_FALTANTE)
NARANJA: Color = (252, 228, 214)  # el mismo de los pendientes (COLOR_PENDIENTE)
ROJO: Color = (248, 215, 218)
GRIS: Color = (238, 238, 238)
GRIS_TEXTO: Color = (110, 110, 110)

PIE = "Demostración · datos de una empresa ficticia (Empresa Ejemplo S.A.S.)"

# Lo que la fuente no tiene, y su reemplazo. Se escriben con su código Unicode porque
# varios son invisibles o se confunden con otros a simple vista.
REEMPLAZOS = {
    # Los emojis de los estados (la palabra del estado ya está en el texto).
    chr(0x2705): "",  # marca verde
    chr(0x26A0): "",  # triángulo de advertencia
    chr(0x26D4): "",  # prohibido
    chr(0xFE0F): "",  # el "selector" invisible que acompaña a algunos emojis
    # Signos tipográficos que latin-1 no tiene.
    chr(0x2014): "-",  # raya
    chr(0x2013): "-",  # guion medio
    chr(0x2026): "...",  # puntos suspensivos
    chr(0x2192): "->",  # flecha
    chr(0x201C): '"',  # comillas dobles tipográficas
    chr(0x201D): '"',
    chr(0x2018): "'",  # comillas simples tipográficas
    chr(0x2019): "'",
    chr(0x00A0): " ",  # espacio duro
}


def legible(texto: str) -> str:
    """El texto listo para el PDF: sin emojis ni marcas de Markdown, y en latin-1."""
    for buscado, reemplazo in REEMPLAZOS.items():
        texto = texto.replace(buscado, reemplazo)
    # Las negritas de Markdown ("**texto**") se quitan, pero NO los asteriscos de un valor
    # enmascarado ("****2345"): por eso el texto en negrita no puede empezar con "*".
    texto = re.sub(r"\*\*([^*].*?)\*\*", r"\1", texto).replace("`", "")
    texto = re.sub(r"^_(.*)_$", r"\1", texto.strip())  # una línea entera en cursiva
    texto = re.sub(r"[ \t]{2,}", " ", texto)  # los saltos de línea se respetan
    return texto.encode("latin-1", "replace").decode("latin-1")


class DocumentoPdf(FPDF):
    """Una hoja A4 con título, subtítulo y un pie que dice que es una demostración."""

    def __init__(self, titulo: str, subtitulo: str = "") -> None:
        super().__init__(format="A4")
        self.set_auto_page_break(auto=True, margin=18)
        self.set_title(legible(titulo))
        self.set_author("Agente Registro como Proveedor")
        self.add_page()
        self.set_font("Helvetica", "B", 16)
        self.multi_cell(0, 8, legible(titulo), new_x="LMARGIN", new_y="NEXT")
        if subtitulo:
            self.set_font("Helvetica", "", 10)
            self.set_text_color(*GRIS_TEXTO)
            self.multi_cell(0, 5, legible(subtitulo), new_x="LMARGIN", new_y="NEXT")
            self.set_text_color(0, 0, 0)
        self.ln(2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*GRIS_TEXTO)
        self.cell(0, 5, legible(f"{PIE} · página {self.page_no()}"), align="C")
        self.set_text_color(0, 0, 0)

    # ---------- Piezas ----------

    def seccion(self, texto: str) -> None:
        self.ln(2)
        self.set_font("Helvetica", "B", 12)
        self.multi_cell(0, 7, legible(texto), new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def parrafo(self, texto: str, *, tamano: int = 10, gris: bool = False) -> None:
        self.set_font("Helvetica", "", tamano)
        if gris:
            self.set_text_color(*GRIS_TEXTO)
        self.multi_cell(0, tamano * 0.5 + 0.5, legible(texto), new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(1.5)

    def vinetas(self, lineas: Sequence[str]) -> None:
        self.set_font("Helvetica", "", 10)
        for linea in lineas:
            self.multi_cell(0, 5.5, legible(f"-  {linea}"), new_x="LMARGIN", new_y="NEXT")
        self.ln(1.5)

    def recuadro(self, texto: str, color: Color, *, negrita: bool = True) -> None:
        """Un aviso en un recuadro de color (por ejemplo, "Listo para firma: Sí")."""
        self.set_font("Helvetica", "B" if negrita else "", 11 if negrita else 10)
        self.set_fill_color(*color)
        self.multi_cell(
            0, 7, legible(texto), border=0, fill=True, padding=2, new_x="LMARGIN", new_y="NEXT"
        )
        self._sin_relleno()
        self.ln(3)

    def _sin_relleno(self) -> None:
        """Vuelve el relleno a blanco: si no, la tabla siguiente heredaría el color."""
        self.set_fill_color(255, 255, 255)

    def tabla(
        self,
        encabezados: Sequence[str],
        filas: Sequence[Sequence[Celda]],
        anchos: Sequence[int] | None = None,
    ) -> None:
        """Una tabla con encabezado gris; cada celda puede llevar su color de fondo."""
        self._sin_relleno()
        self.set_font("Helvetica", "", 9)
        with self.table(
            col_widths=tuple(anchos) if anchos else None,
            headings_style=FontFace(emphasis="BOLD", fill_color=GRIS),
            line_height=5.5,
            text_align="LEFT",
        ) as tabla:
            encabezado = tabla.row()
            for titulo in encabezados:
                encabezado.cell(legible(titulo))
            for fila in filas:
                renglon = tabla.row()
                for celda in fila:
                    texto, color = celda if isinstance(celda, tuple) else (celda, None)
                    estilo = FontFace(fill_color=color) if color else None
                    renglon.cell(legible(texto), style=estilo)
        self.ln(3)

    def en_bytes(self) -> bytes:
        return bytes(self.output())


def desde_markdown(documento: DocumentoPdf, texto: str, *, saltar_titulo: bool = True) -> None:
    """Escribe un texto Markdown sencillo: títulos, párrafos, viñetas, citas y tablas.

    `saltar_titulo`: el primer "# Título" no se repite (ya está como título del PDF).
    """
    lineas = texto.splitlines()
    if saltar_titulo and lineas and lineas[0].startswith("# "):
        lineas = lineas[1:]
    parrafo: list[str] = []
    vinetas: list[str] = []
    tabla: list[str] = []

    def cerrar() -> None:
        if parrafo:
            # Cada línea en su renglón: en un correo, "Para:", "Asunto:" y la firma van
            # en líneas separadas aunque no haya una línea en blanco entre ellas.
            documento.parrafo("\n".join(parrafo))
            parrafo.clear()
        if vinetas:
            documento.vinetas(list(vinetas))
            vinetas.clear()
        if tabla:
            _escribir_tabla(documento, tabla)
            tabla.clear()

    for linea in lineas:
        limpia = linea.strip()
        if limpia.startswith("|") and limpia.endswith("|"):
            if parrafo or vinetas:
                cerrar()
            tabla.append(limpia)
            continue
        if tabla:
            cerrar()
        if not limpia or re.fullmatch(r"-{3,}", limpia):  # vacía, o una raya "---"
            cerrar()
        elif limpia.startswith("#"):
            cerrar()
            documento.seccion(limpia.lstrip("#").strip())
        elif limpia.startswith(">"):
            cerrar()
            documento.recuadro(limpia.lstrip(">").strip(), AMARILLO)
        elif re.match(r"^[-*]\s+", limpia):
            if parrafo:
                cerrar()
            vinetas.append(re.sub(r"^[-*]\s+(\[[ x]\]\s+)?", "", limpia))
        else:
            if vinetas:
                cerrar()
            parrafo.append(limpia)
    cerrar()


def _escribir_tabla(documento: DocumentoPdf, lineas: list[str]) -> None:
    """Una tabla Markdown ("| a | b |", con su línea "|---|") como tabla del PDF."""
    filas = [[c.strip() for c in linea.strip("|").split("|")] for linea in lineas]
    filas = [f for f in filas if not all(re.fullmatch(r":?-{3,}:?", c) for c in f)]
    if not filas:
        return
    documento.tabla(filas[0], filas[1:])
