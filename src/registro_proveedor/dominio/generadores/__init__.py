"""Generadores de formularios: Excel (`excel.py`), PDF (`pdf.py`) y portal (`portal.py`).

Los tres trabajan SOLO con el mapeo guardado (`out/<caso>/mapeo.json`), nunca con
valores que mande el modelo de lenguaje. Lo que comparten está en `comun.py`.

`generar_formulario` elige el generador según el formato del caso. La usan la
herramienta del Paso 7 y el paquete del Paso 8.
"""

from pathlib import Path

from registro_proveedor.dominio.casos import CasoLeido
from registro_proveedor.dominio.generadores.comun import FormularioGenerado
from registro_proveedor.dominio.generadores.excel import generar_excel
from registro_proveedor.dominio.generadores.pdf import generar_pdf
from registro_proveedor.dominio.generadores.portal import generar_portal
from registro_proveedor.dominio.mapeo import Mapeo
from registro_proveedor.dominio.modelos import Formato

GENERADORES = {
    Formato.EXCEL: generar_excel,
    Formato.PDF: generar_pdf,
    Formato.PORTAL: generar_portal,
}


def generar_formulario(mapeo: Mapeo, caso: CasoLeido, carpeta: Path) -> FormularioGenerado:
    """Genera el formulario del formato del caso en `carpeta` y devuelve el resumen."""
    return GENERADORES[caso.formato](mapeo, caso, carpeta)
