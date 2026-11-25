"""Valores para portal: `valores-portal.md`, una tabla "campo → valor" lista para copiar.

El formato portal no se automatiza en el MVP (HU-3): la analista entra al portal del
cliente con sus credenciales y copia cada valor. El texto vive en una plantilla de
Jinja2 (`plantillas/valores-portal.md.j2`), no en el código.

Este archivo SÍ lleva los valores completos, incluida la cuenta bancaria: el portal
los pide. Vive en `out/`, que nunca se le envía al modelo de lenguaje.
"""

from pathlib import Path

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
from registro_proveedor.dominio.textos import renderizar

ARCHIVO_PORTAL = "valores-portal.md"


def generar_portal(mapeo: Mapeo, caso: CasoLeido, carpeta: Path) -> FormularioGenerado:
    """Escribe `valores-portal.md` en la carpeta del caso y devuelve el resumen."""
    lista = escrituras(mapeo)
    texto = renderizar(
        f"{ARCHIVO_PORTAL}.j2",
        cliente=caso.cliente,
        caso=caso.caso,
        generado_en=mapeo.generado_en.date().isoformat(),
        version_maestro=mapeo.version_maestro or "sin versión",
        escrituras=lista,
        estados=TEXTO_ESTADO,
        pendientes=[e.etiqueta for e in lista if e.marca is Marca.PENDIENTE],
        faltantes=[e.etiqueta for e in lista if e.marca is Marca.FALTANTE],
    )
    destino = carpeta / ARCHIVO_PORTAL
    escribir_atomico(destino, lambda ruta: ruta.write_text(texto, encoding="utf-8", newline="\n"))
    return resumen(destino, lista)
