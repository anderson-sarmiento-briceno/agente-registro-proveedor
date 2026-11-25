"""Pruebas de `dominio/generadores/`: Excel, PDF y valores para portal.

Cada prueba genera el archivo en una carpeta temporal y lo vuelve a ABRIR para revisar
lo que quedó escrito: el Excel con openpyxl (celda por celda), el PDF con pypdf (su
texto) y el Markdown como texto.

Recordatorio de la regla (HU-3): lleno → valor · faltante → vacío y amarillo ·
por confirmar → vacío y naranja.
"""

from pathlib import Path

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from registro_proveedor.config import RAIZ_PROYECTO
from registro_proveedor.dominio.casos import CasoLeido, leer_caso
from registro_proveedor.dominio.generadores.comun import (
    COLOR_FALTANTE,
    COLOR_PENDIENTE,
    ErrorDeGeneracion,
    verificar_correspondencia,
)
from registro_proveedor.dominio.generadores.excel import generar_excel
from registro_proveedor.dominio.generadores.pdf import generar_pdf, latin1
from registro_proveedor.dominio.generadores.portal import generar_portal
from registro_proveedor.dominio.lectura import cargar_glosario, cargar_maestro
from registro_proveedor.dominio.mapeo import Decision, Mapeo, confirmar_campo, mapear_caso
from registro_proveedor.dominio.modelos import Maestro
from registro_proveedor.dominio.reglas import cargar_reglas
from registro_proveedor.dominio.textos import celda_md
from tests.ayudas import DATOS_REALES, FECHA_FIJA, HORA_FIJA

GLOSARIO = cargar_glosario(DATOS_REALES)
MAESTRO = cargar_maestro(DATOS_REALES)
REGLAS = cargar_reglas(RAIZ_PROYECTO / "config" / "reglas.yaml")


def _mapeo(caso: str, maestro: Maestro = MAESTRO) -> tuple[Mapeo, CasoLeido]:
    leido = leer_caso(DATOS_REALES, caso)
    return mapear_caso(leido, GLOSARIO, maestro, REGLAS, HORA_FIJA, FECHA_FIJA), leido


def _relleno(celda: object) -> str:
    """El color de fondo de una celda de openpyxl, como "FFF2CC" (sin el canal alfa)."""
    color = str(celda.fill.fgColor.rgb)  # type: ignore[attr-defined]
    return color[-6:]


# ---------- Excel ----------


def test_excel_celdas_exactas_en_dos_hojas(tmp_path: Path) -> None:
    m, caso = _mapeo("co-industrias-delta")
    generado = generar_excel(m, caso, tmp_path)
    assert generado.ruta.name == "formulario.xlsx"
    assert (generado.escritos, generado.faltantes, generado.pendientes) == (17, 0, 0)

    libro = load_workbook(generado.ruta)
    assert libro.sheetnames == ["Datos Proveedor", "Datos Bancarios"]  # en orden de aparición
    proveedor = libro["Datos Proveedor"]
    assert proveedor["B3"].value == "Razón social"
    assert proveedor["B3"].font.bold
    assert proveedor["C3"].value == "Empresa Ejemplo S.A.S."
    assert proveedor["C4"].value == "900123456"
    banco = libro["Datos Bancarios"]
    assert (banco["B5"].value, banco["C5"].value) == ("Número de cuenta", "03100012345")


def test_excel_todo_es_texto(tmp_path: Path) -> None:
    """El código postal conserva su cero y el NIT no se vuelve número."""
    m, caso = _mapeo("co-industrias-delta")
    hoja = load_workbook(generar_excel(m, caso, tmp_path).ruta)["Datos Proveedor"]
    assert hoja["C8"].value == "050021"  # Código postal
    assert hoja["C8"].data_type == "s"
    assert hoja["C4"].data_type == "s"  # NIT


def test_excel_faltante_y_pendiente_vacios_y_resaltados(tmp_path: Path) -> None:
    m, caso = _mapeo("hn-agroexport-sula")
    generado = generar_excel(m, caso, tmp_path)
    assert (generado.escritos, generado.faltantes, generado.pendientes) == (9, 1, 1)
    hoja = load_workbook(generado.ruta)["Registro"]

    rtn = hoja["B3"]  # RTN: por confirmar (RN1)
    assert rtn.value is None
    assert _relleno(rtn) == COLOR_PENDIENTE
    assert rtn.comment is not None
    assert rtn.comment.text.startswith("Pendiente de confirmación: ")
    assert "identificador extranjero" in rtn.comment.text

    referencias = hoja["B12"]  # Referencias comerciales: faltante
    assert referencias.value is None  # vacío: nunca un texto de relleno
    assert _relleno(referencias) == COLOR_FALTANTE
    assert referencias.comment is not None
    assert referencias.comment.text.startswith("Falta: la etiqueta no está en el glosario")


def test_excel_despues_de_confirmar_sale_el_valor(tmp_path: Path) -> None:
    m, caso = _mapeo("hn-agroexport-sula")
    confirmado, _ = confirmar_campo(m, "RTN", Decision.ACEPTAR, "analista", HORA_FIJA)
    hoja = load_workbook(generar_excel(confirmado, caso, tmp_path).ruta)["Registro"]
    assert hoja["B3"].value == "900123456"
    assert hoja["B3"].comment is None


def test_excel_un_valor_con_igual_no_es_formula(tmp_path: Path) -> None:
    """Inyección de fórmulas: un "=" al inicio no debe ejecutarse al abrir el archivo."""
    peligroso = '=HYPERLINK("http://sitio-malo.example","clic")'
    maestro = MAESTRO.model_copy(update={"razon_social": peligroso})
    m, caso = _mapeo("co-industrias-delta", maestro)
    celda = load_workbook(generar_excel(m, caso, tmp_path).ruta)["Datos Proveedor"]["C3"]
    assert celda.value == peligroso
    assert celda.data_type == "s"  # "s" = texto; una fórmula sería "f"


def test_excel_fecha_interna_es_la_del_mapeo(tmp_path: Path) -> None:
    m, caso = _mapeo("co-industrias-delta")
    libro = load_workbook(generar_excel(m, caso, tmp_path).ruta)
    assert libro.properties.created == HORA_FIJA.replace(tzinfo=None)


def test_excel_sin_celdas_en_el_mapeo(tmp_path: Path) -> None:
    m, caso = _mapeo("ec-corp-andina")  # un mapeo de PDF no tiene hojas ni celdas
    with pytest.raises(ErrorDeGeneracion, match="no tiene hoja o celda"):
        generar_excel(m, caso, tmp_path)


def test_no_quedan_archivos_temporales(tmp_path: Path) -> None:
    m, caso = _mapeo("co-industrias-delta")
    generar_excel(m, caso, tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["formulario.xlsx"]


# ---------- PDF ----------


def _texto_pdf(ruta: Path) -> str:
    return "\n".join(pagina.extract_text() for pagina in PdfReader(ruta).pages)


def test_pdf_campos_en_orden_con_obligatorios(tmp_path: Path) -> None:
    m, caso = _mapeo("ec-corp-andina")
    generado = generar_pdf(m, caso, tmp_path)
    assert generado.ruta.name == "formulario.pdf"
    assert (generado.escritos, generado.faltantes, generado.pendientes) == (13, 1, 1)

    texto = _texto_pdf(generado.ruta)
    assert "Formulario de registro de proveedor" in texto
    assert "Cliente: Corporación Andina de Servicios S.A." in texto
    assert "Nombre de la empresa * Empresa Ejemplo S.A.S." in texto
    assert "Página web https://www.empresa-ejemplo.com" in texto  # no obligatorio: sin "*"
    # El orden es el de la plantilla.
    posiciones = [texto.index(c.etiqueta) for c in caso.campos]
    assert posiciones == sorted(posiciones)


def test_pdf_lo_pendiente_y_lo_faltante_quedan_vacios(tmp_path: Path) -> None:
    m, caso = _mapeo("ec-corp-andina")
    texto = _texto_pdf(generar_pdf(m, caso, tmp_path).ruta)
    assert "900123456" not in texto  # el RUC (NIT) está por confirmar: no se escribe
    lineas = texto.splitlines()
    assert "RUC *" in lineas  # la etiqueta sola, sin valor
    assert "Número de contribuyente especial" in lineas


def test_pdf_despues_de_confirmar_sale_el_valor(tmp_path: Path) -> None:
    m, caso = _mapeo("ec-corp-andina")
    confirmado, _ = confirmar_campo(m, "RUC", Decision.ACEPTAR, "analista", HORA_FIJA)
    assert "RUC * 900123456" in _texto_pdf(generar_pdf(confirmado, caso, tmp_path).ruta)


def test_latin1() -> None:
    assert latin1("Razón social: ñandú ¿?") == "Razón social: ñandú ¿?"  # el español pasa igual
    assert latin1("Precio — 5 €") == "Precio ? 5 ?"  # lo que la fuente no tiene, se reemplaza


# ---------- Portal ----------


def test_portal_tabla_para_copiar(tmp_path: Path) -> None:
    m, caso = _mapeo("pa-logistica-istmo")
    generado = generar_portal(m, caso, tmp_path)
    assert generado.ruta.name == "valores-portal.md"
    assert (generado.escritos, generado.faltantes, generado.pendientes) == (8, 0, 1)

    texto = generado.ruta.read_text(encoding="utf-8")
    assert texto.startswith("# Valores para el portal · Logística del Istmo S.A.\n")
    assert "| 1 | Nombre o razón social del proveedor * | Empresa Ejemplo S.A.S. | listo |" in texto
    assert "| 2 | RUC * |  | PENDIENTE de confirmación |" in texto
    # El portal pide la cuenta completa: este archivo es para la analista, no para el modelo.
    assert "| 8 | Número de cuenta * | 03100012345 | listo |" in texto
    assert "**Pendientes de confirmación:** RUC." in texto
    assert "Faltan en el maestro" not in texto  # no hay faltantes en este caso
    assert "{#" not in texto and "#}" not in texto  # los comentarios de la plantilla no salen
    assert texto.endswith("\n")


def test_portal_con_faltantes(tmp_path: Path) -> None:
    sin_swift = MAESTRO.model_copy(
        update={"banco": MAESTRO.banco.model_copy(update={"swift": None})}  # type: ignore[union-attr]
    )
    m, caso = _mapeo("pa-logistica-istmo", sin_swift)
    texto = generar_portal(m, caso, tmp_path).ruta.read_text(encoding="utf-8")
    assert "| 9 | SWIFT * |  | FALTA en el maestro |" in texto
    assert "**Faltan en el maestro:** SWIFT." in texto


def test_celda_md() -> None:
    assert celda_md("A | B") == "A \\| B"  # un "|" cortaría la columna
    assert celda_md("línea 1\nlínea 2") == "línea 1 línea 2"  # un salto cortaría la fila


# ---------- Correspondencia entre mapeo y plantilla ----------


def test_correspondencia_correcta() -> None:
    m, caso = _mapeo("co-industrias-delta")
    verificar_correspondencia(m, caso)  # no lanza


def test_mapeo_de_otro_caso() -> None:
    m, _ = _mapeo("co-industrias-delta")
    _, otro = _mapeo("hn-agroexport-sula")
    with pytest.raises(ErrorDeGeneracion, match="no corresponde a la plantilla actual"):
        verificar_correspondencia(m, otro)


def test_plantilla_cambiada_despues_de_mapear() -> None:
    m, caso = _mapeo("co-industrias-delta")
    movida = caso.campos[0].model_copy(update={"celda": "D3"})
    cambiado = caso.model_copy(update={"campos": [movida, *caso.campos[1:]]})
    with pytest.raises(ErrorDeGeneracion, match="vuelva a usar proveedor_mapear_campos"):
        verificar_correspondencia(m, cambiado)
