"""Formulario Excel: cada etiqueta y su valor en la hoja y la celda exactas de la plantilla.

Se crea un libro nuevo (los datos de ejemplo traen la plantilla en JSON, no el .xlsx
del cliente). Si en producción llega el archivo original, lo correcto sería abrirlo
y escribir encima, para respetar su formato (pendiente anotado en SOLUCION.md).

Dos protecciones:
    1. Todo se escribe como TEXTO. Si no, "050021" (código postal) perdería el cero
       y el NIT se convertiría en número.
    2. Un valor que empiece con "=" no se vuelve fórmula. Si alguien pusiera
       "=HIPERVINCULO(...)" en el maestro, Excel lo ejecutaría al abrir el archivo
       ("inyección de fórmulas").
"""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import Cell
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string, get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from registro_proveedor.dominio.casos import CasoLeido
from registro_proveedor.dominio.generadores.comun import (
    COLOR_FALTANTE,
    COLOR_PENDIENTE,
    ErrorDeGeneracion,
    Escritura,
    FormularioGenerado,
    Marca,
    escribir_atomico,
    escrituras,
    resumen,
)
from registro_proveedor.dominio.mapeo import Mapeo

ARCHIVO_EXCEL = "formulario.xlsx"
AUTOR = "Agente Registro como Proveedor"
RELLENOS = {
    Marca.FALTANTE: PatternFill("solid", fgColor=COLOR_FALTANTE),
    Marca.PENDIENTE: PatternFill("solid", fgColor=COLOR_PENDIENTE),
}


def generar_excel(mapeo: Mapeo, caso: CasoLeido, carpeta: Path) -> FormularioGenerado:
    """Escribe `formulario.xlsx` en la carpeta del caso y devuelve el resumen."""
    lista = escrituras(mapeo)
    libro = Workbook()
    libro.remove(libro.active)  # type: ignore[arg-type]  # se quita la hoja vacía por defecto
    hojas: dict[str, Worksheet] = {}
    for e in lista:
        hoja = _hoja(libro, hojas, e)
        _escribir_campo(hoja, e)
    for hoja in hojas.values():
        _ajustar_anchos(hoja)
    # Fecha interna del archivo = fecha del mapeo (no la hora actual), para que dos
    # ejecuciones con el mismo mapeo den el mismo contenido. Sin zona horaria, porque
    # openpyxl la escribe mal; el mapeo ya está en UTC.
    fecha = mapeo.generado_en.replace(tzinfo=None)
    libro.properties.created = fecha
    libro.properties.modified = fecha
    libro.properties.creator = AUTOR
    libro.properties.title = f"Registro de proveedor - {caso.cliente}"
    destino = carpeta / ARCHIVO_EXCEL
    escribir_atomico(destino, lambda ruta: libro.save(ruta))
    return resumen(destino, lista)


def _hoja(libro: Workbook, hojas: dict[str, Worksheet], e: Escritura) -> Worksheet:
    """La hoja del campo, creándola la primera vez (en el orden en que aparecen)."""
    if e.hoja is None or e.celda is None or e.celda_etiqueta is None:
        raise ErrorDeGeneracion(
            f"el campo «{e.etiqueta}» no tiene hoja o celda en el mapeo: "
            "vuelva a usar proveedor_mapear_campos"
        )
    if e.hoja not in hojas:
        hojas[e.hoja] = libro.create_sheet(e.hoja)
    return hojas[e.hoja]


def _escribir_campo(hoja: Worksheet, e: Escritura) -> None:
    assert e.celda is not None and e.celda_etiqueta is not None  # lo comprobó `_hoja`
    etiqueta = hoja[e.celda_etiqueta]
    _texto(etiqueta, e.etiqueta + (" *" if e.obligatorio else ""))
    etiqueta.font = Font(bold=True)

    valor = hoja[e.celda]
    _texto(valor, e.valor)
    if e.marca in RELLENOS:
        valor.fill = RELLENOS[e.marca]
    if e.comentario:
        valor.comment = Comment(e.comentario, AUTOR)


def _texto(celda: Cell, texto: str | None) -> None:
    """Escribe un texto que Excel NUNCA interpretará como número ni como fórmula."""
    celda.value = texto
    if texto is not None:
        celda.data_type = "s"  # "s" = string: aunque empiece con "=", es texto
    celda.number_format = "@"  # formato de celda "Texto"


def _ajustar_anchos(hoja: Worksheet) -> None:
    """Ancho de cada columna según su texto más largo (con un mínimo y un máximo)."""
    anchos: dict[int, int] = {}
    for fila in hoja.iter_rows():
        for celda in fila:
            if celda.value is not None:
                columna = column_index_from_string(coordinate_from_string(celda.coordinate)[0])
                anchos[columna] = max(anchos.get(columna, 0), len(str(celda.value)))
    for columna, ancho in anchos.items():
        hoja.column_dimensions[get_column_letter(columna)].width = min(max(ancho + 2, 12), 80)
