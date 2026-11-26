"""Valores para portal: `valores-portal.md`, una tabla "campo → valor" lista para copiar.

El formato portal no se automatiza en el MVP (HU-3): la analista entra al portal del
cliente con sus credenciales y copia cada valor. El texto vive en una plantilla de
Jinja2 (`plantillas/valores-portal.md.j2`), no en el código.

Este archivo SÍ lleva los valores completos, incluida la cuenta bancaria: el portal
los pide. Vive en `out/`, que nunca se le envía al modelo de lenguaje.
"""

from dataclasses import dataclass
from pathlib import Path

from registro_proveedor.dominio.casos import CasoLeido
from registro_proveedor.dominio.generadores.comun import (
    TEXTO_ESTADO,
    FormularioGenerado,
    Marca,
    escribir_atomico,
    escrituras,
    que_escribir,
    resumen,
)
from registro_proveedor.dominio.mapeo import Mapeo
from registro_proveedor.dominio.textos import renderizar
from registro_proveedor.observabilidad import enmascarar, es_ruta_sensible

ARCHIVO_PORTAL = "valores-portal.md"


@dataclass(frozen=True)
class ValorParaCopiar:
    """Un campo del portal como se muestra en la página, con su botón Copiar (Paso 18, D57)."""

    etiqueta: str
    valor: str | None  # None = no hay nada que copiar (faltante o por confirmar)
    estado: str  # "listo", "FALTA en el maestro", "PENDIENTE de confirmación"
    enmascarado: bool  # True = dato sensible: se muestra "****2345", no se puede copiar


def valores_para_copiar(mapeo: Mapeo) -> list[ValorParaCopiar]:
    """Los valores del portal para la PÁGINA, que es pública (D65): lo sensible, enmascarado.

    La demo no tiene clave de acceso, así que la cuenta bancaria y la identificación del
    representante nunca salen completas por aquí (RN8). Para esos campos la analista
    abre `valores-portal.md` en `out/`, que sí los tiene completos.
    """
    lista: list[ValorParaCopiar] = []
    for campo in mapeo.campos:
        escritura = que_escribir(campo)
        sensible = campo.ruta is not None and es_ruta_sensible(campo.ruta)
        valor = escritura.valor
        lista.append(
            ValorParaCopiar(
                etiqueta=escritura.etiqueta,
                valor=enmascarar(valor) if sensible and valor is not None else valor,
                estado=TEXTO_ESTADO[escritura.marca],
                enmascarado=sensible and valor is not None,
            )
        )
    return lista


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
