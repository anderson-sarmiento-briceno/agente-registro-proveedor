"""El paquete de un caso como un .zip, para descargarlo desde el chat de la demo (Paso 19).

¿Por qué?
    En la demo publicada (Render) nadie puede entrar a las carpetas del servidor: `out/`
    no se sirve a internet y, además, se borra cuando el servicio se apaga. Para que
    quien prueba la demo VEA el resultado, el chat ofrece un botón "Descargar paquete
    (.zip)" con lo que se armó para el caso.

Qué lleva el zip (dentro de una carpeta con el nombre del caso):
    - los soportes copiados al paquete (los vencidos también: el checklist lo dice);
    - checklist.md, borrador-correo.md y manifiesto.json;
    - constancia-envio.md, si ya se registró el envío;
    - LEEME.txt, que explica qué se dejó fuera y por qué.

Qué NO lleva: el formulario lleno (formulario.xlsx, formulario.pdf, valores-portal.md).
    Tiene la cuenta bancaria COMPLETA, y la demo es una página abierta, sin clave (D65):
    nunca debe entregar un dato sensible completo (RN8, D68). Una prueba revisa que el
    zip no contenga la cuenta.

En producción esto no sería una descarga desde el chat: el paquete quedaría guardado
en un repositorio documental, con acceso por usuario, seguimiento y trazabilidad (ver
SOLUCION.md, B8 y C).
"""

import io
import zipfile
from pathlib import Path

from registro_proveedor.dominio.envio import ARCHIVO_ENVIO
from registro_proveedor.dominio.generadores.excel import ARCHIVO_EXCEL
from registro_proveedor.dominio.generadores.pdf import ARCHIVO_PDF
from registro_proveedor.dominio.generadores.portal import ARCHIVO_PORTAL
from registro_proveedor.dominio.paquete import CARPETA_PAQUETE

# Los archivos que llevan los valores completos del maestro: nunca van en la descarga.
CON_DATOS_COMPLETOS = frozenset({ARCHIVO_EXCEL, ARCHIVO_PDF, ARCHIVO_PORTAL})
ARCHIVO_LEEME = "LEEME.txt"

LEEME = """Paquete de registro como proveedor · {caso}

Esta descarga es de la DEMOSTRACIÓN (datos de la empresa ficticia «Empresa Ejemplo S.A.S.»).

Incluye los soportes copiados al paquete, el checklist (qué está listo y qué no), el
borrador del correo al cliente, el manifiesto (huellas y origen de cada campo) y, si ya
se registró el envío, la constancia.

No incluye el formulario lleno ({formulario}): trae la cuenta bancaria completa, y la
demostración es una página abierta. En producción, el paquete completo queda en un
repositorio documental con acceso por usuario y trazabilidad.
"""


def zip_del_paquete(carpeta_caso: Path) -> bytes | None:
    """El zip del paquete del caso, en memoria. None si todavía no se armó el paquete."""
    paquete = carpeta_caso / CARPETA_PAQUETE
    if not paquete.is_dir():
        return None
    caso = carpeta_caso.name
    archivos = sorted(p for p in paquete.iterdir() if p.is_file())
    constancia = carpeta_caso / ARCHIVO_ENVIO
    if constancia.is_file():
        archivos.append(constancia)
    excluidos = sorted(p.name for p in archivos if p.name in CON_DATOS_COMPLETOS)

    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", compression=zipfile.ZIP_DEFLATED) as destino:
        for archivo in archivos:
            if archivo.name not in CON_DATOS_COMPLETOS:
                destino.write(archivo, arcname=f"{caso}/{archivo.name}")
        leeme = LEEME.format(caso=caso, formulario=", ".join(excluidos) or "formulario")
        destino.writestr(f"{caso}/{ARCHIVO_LEEME}", leeme)
    return memoria.getvalue()
