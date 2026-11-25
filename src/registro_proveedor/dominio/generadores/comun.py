"""Lo que comparten los tres generadores: qué se escribe en cada campo y las comprobaciones previas.

La regla central (HU-3):
    - lleno                  → se escribe el valor.
    - faltante               → queda VACÍO y resaltado (amarillo). Nunca un texto de relleno.
    - requiere_confirmacion  → queda VACÍO y resaltado (naranja): un valor que la analista
                               no ha aprobado no debe aparecer en un documento que va a firma.
                               Cuando lo confirme, se vuelve a generar el formulario.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from registro_proveedor.dominio.casos import CasoLeido
from registro_proveedor.dominio.mapeo import CampoMapeado, Estado, Mapeo


class ErrorDeGeneracion(Exception):
    """No se puede generar el formulario; el mensaje dice qué hacer."""


class Marca(StrEnum):
    """Cómo se presenta un campo en el formulario."""

    VALOR = "valor"  # se escribe el valor
    FALTANTE = "faltante"  # vacío, amarillo
    PENDIENTE = "pendiente"  # vacío, naranja


# Colores de resaltado (RGB en hexadecimal), iguales en Excel y en PDF.
COLOR_FALTANTE = "FFF2CC"  # amarillo claro
COLOR_PENDIENTE = "FCE4D6"  # naranja claro

TEXTO_ESTADO = {
    Marca.VALOR: "listo",
    Marca.FALTANTE: "FALTA en el maestro",
    Marca.PENDIENTE: "PENDIENTE de confirmación",
}


@dataclass(frozen=True)
class Escritura:
    """Lo que se escribe para un campo: su etiqueta, su valor (o nada) y cómo marcarlo."""

    etiqueta: str
    obligatorio: bool | None
    hoja: str | None
    celda_etiqueta: str | None
    celda: str | None
    valor: str | None  # None = la celda queda vacía
    marca: Marca
    comentario: str | None  # explicación para la analista (en Excel, un comentario de celda)


def que_escribir(campo: CampoMapeado) -> Escritura:
    """Decide qué se escribe para un campo, según su estado."""
    if campo.estado is Estado.LLENO:
        marca, valor, comentario = Marca.VALOR, campo.valor, None
    elif campo.estado is Estado.FALTANTE:
        marca, valor, comentario = Marca.FALTANTE, None, f"Falta: {campo.nota}"
    else:
        marca, valor = Marca.PENDIENTE, None
        comentario = f"Pendiente de confirmación: {campo.nota}"
    return Escritura(
        etiqueta=campo.etiqueta,
        obligatorio=campo.obligatorio,
        hoja=campo.hoja,
        celda_etiqueta=campo.celda_etiqueta,
        celda=campo.celda,
        valor=valor,
        marca=marca,
        comentario=comentario,
    )


def escrituras(mapeo: Mapeo) -> list[Escritura]:
    """Las escrituras de todos los campos, en el orden de la plantilla."""
    return [que_escribir(c) for c in mapeo.campos]


def verificar_correspondencia(mapeo: Mapeo, caso: CasoLeido) -> None:
    """Comprueba que el mapeo guardado sea de ESTA plantilla, campo por campo y en orden.

    Si alguien cambió la plantilla después de mapear (agregó un campo, movió una celda),
    generar con el mapeo viejo daría un formulario descuadrado. En ese caso se pide
    volver a mapear.
    """
    # La "huella" de cada campo: etiqueta, hoja, celda de la etiqueta y celda del valor.
    del_mapeo = [(c.etiqueta, c.hoja, c.celda_etiqueta, c.celda) for c in mapeo.campos]
    de_plantilla = [(c.etiqueta, c.hoja, c.celda_etiqueta, c.celda) for c in caso.campos]
    if mapeo.caso != caso.caso or del_mapeo != de_plantilla:
        raise ErrorDeGeneracion(
            "el mapeo guardado no corresponde a la plantilla actual del caso "
            "(¿cambió la plantilla después de mapear?): vuelva a usar proveedor_mapear_campos"
        )


class FormularioGenerado(BaseModel):
    """El resultado de un generador: dónde quedó el archivo y cuántos campos de cada tipo."""

    model_config = ConfigDict(frozen=True)

    ruta: Path
    escritos: int
    faltantes: int
    pendientes: int


def resumen(ruta: Path, lista: list[Escritura]) -> FormularioGenerado:
    def contar(marca: Marca) -> int:
        return sum(1 for e in lista if e.marca is marca)

    return FormularioGenerado(
        ruta=ruta,
        escritos=contar(Marca.VALOR),
        faltantes=contar(Marca.FALTANTE),
        pendientes=contar(Marca.PENDIENTE),
    )


def escribir_atomico(destino: Path, escribir: Callable[[Path], object]) -> None:
    """Escribe el archivo en un temporal y después lo pone en su lugar de una sola vez.

    Si algo falla a mitad de camino, no queda un formulario a medio escribir que
    alguien podría mandar a firma por error.
    """
    temporal = destino.with_name(f".{destino.name}.tmp")
    escribir(temporal)
    os.replace(temporal, destino)
