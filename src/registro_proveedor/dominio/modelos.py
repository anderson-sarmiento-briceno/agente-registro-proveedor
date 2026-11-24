"""Modelos de los insumos de `datos/`: solicitud, plantillas, soportes, maestro y glosario.

Dos tipos de modelo:
- `ModeloEstricto`: archivos del caso y del índice. Un campo desconocido es un error,
  porque casi siempre es un error de escritura (`celda_valr`).
- `ModeloTolerante`: el maestro. Un campo desconocido se acepta y queda en
  `model_extra`; la validación lo reporta como sugerencia para el dueño del dato.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# ---------- Patrones (cada uno tiene su pista en `lectura.PISTAS_PATRON`) ----------

PATRON_ID_CASO = r"^[a-z0-9]+(-[a-z0-9]+)*$"
PATRON_CELDA = r"^[A-Z]{1,3}[1-9][0-9]*$"
PATRON_HOJA = r"^[^\[\]:*?/\\]+$"
PATRON_ARCHIVO = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
PATRON_RUTA_MAESTRO = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"

# ---------- Tipos reutilizables ----------

TextoNoVacio = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
IdCaso = Annotated[str, StringConstraints(pattern=PATRON_ID_CASO)]
Celda = Annotated[str, StringConstraints(pattern=PATRON_CELDA)]
NombreHoja = Annotated[str, StringConstraints(min_length=1, max_length=31, pattern=PATRON_HOJA)]
NombreArchivo = Annotated[str, StringConstraints(pattern=PATRON_ARCHIVO)]
RutaMaestro = Annotated[str, StringConstraints(pattern=PATRON_RUTA_MAESTRO)]


class Pais(StrEnum):
    COLOMBIA = "CO"
    ECUADOR = "EC"
    PERU = "PE"
    PANAMA = "PA"
    HONDURAS = "HN"


class Formato(StrEnum):
    EXCEL = "xlsx"
    PDF = "pdf"
    PORTAL = "portal"


class TipoSoporte(StrEnum):
    CAMARA_COMERCIO = "camara_comercio"
    RUT = "rut"
    CERTIFICACION_BANCARIA = "certificacion_bancaria"
    PARAFISCALES = "parafiscales"
    ESTADOS_FINANCIEROS = "estados_financieros"
    CERTIFICADO_ISO_9001 = "certificado_iso_9001"
    CERTIFICADO_CUMPLIMIENTO_TRIBUTARIO = "certificado_cumplimiento_tributario"


class ModeloEstricto(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModeloTolerante(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


# ---------- Archivos de un caso: datos/casos/<caso>/ ----------


class Solicitud(ModeloEstricto):
    """`solicitud.json`: el correo del cliente, ya normalizado."""

    id: IdCaso
    de: TextoNoVacio
    para: TextoNoVacio | None = None
    asunto: TextoNoVacio
    fecha: date
    pais: Pais
    cliente: TextoNoVacio
    formato: Formato
    cuerpo: str
    adjuntos: list[TextoNoVacio] = Field(default_factory=list)


class CeldaPlantilla(ModeloEstricto):
    """Un elemento de `plantilla-celdas.json` (formato Excel)."""

    hoja: NombreHoja
    celda_etiqueta: Celda
    etiqueta: TextoNoVacio
    celda_valor: Celda


class CampoPlantilla(ModeloEstricto):
    """Un elemento de `plantilla-campos.json` (formato PDF o portal)."""

    etiqueta: TextoNoVacio
    obligatorio: bool


# ---------- Repositorio: datos/repositorio/ ----------


class Soporte(ModeloEstricto):
    """Un elemento de `soportes/index.json`."""

    tipo: TipoSoporte
    archivo: NombreArchivo
    vigencia_hasta: date | None
    pais_emisor: Pais
    descripcion: TextoNoVacio


class RepresentanteLegal(ModeloTolerante):
    nombre: TextoNoVacio | None = None
    tipo_identificacion: TextoNoVacio | None = None
    identificacion: TextoNoVacio | None = None
    cargo: TextoNoVacio | None = None
    email: TextoNoVacio | None = None


class Contacto(ModeloTolerante):
    nombre: TextoNoVacio | None = None
    cargo: TextoNoVacio | None = None
    email: TextoNoVacio | None = None
    telefono: TextoNoVacio | None = None


class Banco(ModeloTolerante):
    nombre: TextoNoVacio | None = None
    tipo_cuenta: TextoNoVacio | None = None
    numero_cuenta: TextoNoVacio | None = None
    titular: TextoNoVacio | None = None
    swift: TextoNoVacio | None = None
    moneda: TextoNoVacio | None = None


class Ingresos(ModeloTolerante):
    valor: Decimal | None = None
    moneda: TextoNoVacio | None = None
    ano: int | None = None


class Maestro(ModeloTolerante):
    """`maestro.json`: los datos de la empresa.

    Solo `razon_social` y `nit` son obligatorios: sin ellos no hay nada que registrar.
    Los demás son opcionales: si faltan, el campo del formulario queda `faltante`
    y la validación lo sugiere al dueño del dato. Nunca se inventa un valor.
    """

    # Recomendados para la trazabilidad (HU-7); los datos de ejemplo no los tienen.
    version: TextoNoVacio | None = None
    actualizado_en: date | None = None

    razon_social: TextoNoVacio
    nit: TextoNoVacio
    tipo_sociedad: TextoNoVacio | None = None
    digito_verificacion: TextoNoVacio | None = None
    pais: Pais | None = None
    ciudad: TextoNoVacio | None = None
    departamento: TextoNoVacio | None = None
    direccion: TextoNoVacio | None = None
    codigo_postal: TextoNoVacio | None = None
    telefono: TextoNoVacio | None = None
    sitio_web: TextoNoVacio | None = None
    fecha_constitucion: date | None = None
    matricula_mercantil: TextoNoVacio | None = None
    ciiu_principal: TextoNoVacio | None = None
    ciiu_secundario: TextoNoVacio | None = None
    actividad_economica: TextoNoVacio | None = None
    regimen_tributario: TextoNoVacio | None = None
    gran_contribuyente: bool | None = None
    autorretenedor: bool | None = None
    numero_empleados: int | None = None
    ingresos_ultimo_ano: Ingresos | None = None
    certificaciones: list[TextoNoVacio] | None = None
    representante_legal: RepresentanteLegal | None = None
    contacto_comercial: Contacto | None = None
    contacto_financiero: Contacto | None = None
    banco: Banco | None = None


# `glosario-campos.json`: etiqueta del cliente → ruta en el maestro (ej. "banco.swift").
Glosario = dict[TextoNoVacio, RutaMaestro]
