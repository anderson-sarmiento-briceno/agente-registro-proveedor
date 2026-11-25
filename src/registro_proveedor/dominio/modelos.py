"""Modelos de los insumos de `datos/`: solicitud, plantillas, soportes, maestro y glosario.

¿Qué es un modelo?
    Una clase que describe la forma de un dato: qué campos tiene y de qué tipo es
    cada uno. Pydantic usa esa descripción como un molde. Al leer un JSON, compara
    su contenido con el molde, convierte lo que puede (el texto "2026-08-25" pasa a
    ser una fecha de verdad) y rechaza lo que no encaja, explicando por qué.

    Este archivo solo describe. No lee archivos: eso lo hace `lectura.py`.

Dos tipos de modelo:
    - `ModeloEstricto` (archivos del caso y del índice de soportes): un campo que no
      está en el molde es un error, porque casi siempre es un error de escritura
      (`celda_valr` en vez de `celda_valor`).
    - `ModeloTolerante` (el maestro): un campo desconocido se acepta y se guarda
      aparte, en `model_extra`. La validación lo reporta como sugerencia para el
      dueño del dato, porque el maestro puede crecer con datos nuevos y eso no debe
      romper todo el proceso.

Todos los modelos son `frozen=True` (inmutables): una vez leído, un dato no se
puede cambiar por accidente en otra parte del código.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# ---------- Patrones ----------
# Expresiones regulares que deben cumplir algunos textos.
#   ^ = inicio del texto · $ = fin · [a-z] = una letra minúscula · + = una o más veces
#   * = cero o más veces · {1,3} = entre 1 y 3 veces · ( ... )* = el grupo, cero o más veces
# Cada patrón tiene una pista en español en `lectura.PISTAS_PATRON`, que se muestra
# cuando un valor no lo cumple.
#
# Nota: Pydantic evalúa estos patrones con un motor (escrito en Rust) que no admite
# "lookahead" (`(?!...)`). Por eso son simples.

# Nombre de la carpeta de un caso: "co-industrias-delta". Sin espacios, mayúsculas
# ni puntos, así que tampoco puede ser "../" (protección de rutas).
PATRON_ID_CASO = r"^[a-z0-9]+(-[a-z0-9]+)*$"

# Celda de Excel en formato A1: de 1 a 3 letras mayúsculas (columna, hasta "XFD") y
# un número que empieza en 1 (fila). "B3" sí; "C0", "3B" o "b3" no.
PATRON_CELDA = r"^[A-Z]{1,3}[1-9][0-9]*$"

# Nombre de hoja de Excel: Excel prohíbe los caracteres [ ] : * ? / \
PATRON_HOJA = r"^[^\[\]:*?/\\]+$"

# Nombre de archivo de un soporte: sin "/" ni "\" (no puede apuntar a otra carpeta) y
# empezando por letra o número (así tampoco puede ser ".." ni un archivo oculto).
PATRON_ARCHIVO = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"

# Ruta dentro del maestro: nombres en snake_case separados por puntos ("banco.swift").
PATRON_RUTA_MAESTRO = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"

# ---------- Tipos reutilizables ----------
# `Annotated[str, ...]` es un texto con reglas extra. Se definen una vez aquí y se
# usan en varios modelos, para que la regla sea la misma en todas partes.

# Texto al que se le quitan los espacios de los extremos y que no puede quedar vacío.
# "  " se rechaza igual que "".
TextoNoVacio = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
IdCaso = Annotated[str, StringConstraints(pattern=PATRON_ID_CASO)]
Celda = Annotated[str, StringConstraints(pattern=PATRON_CELDA)]
# Excel no permite nombres de hoja de más de 31 caracteres.
NombreHoja = Annotated[str, StringConstraints(min_length=1, max_length=31, pattern=PATRON_HOJA)]
NombreArchivo = Annotated[str, StringConstraints(pattern=PATRON_ARCHIVO)]
RutaMaestro = Annotated[str, StringConstraints(pattern=PATRON_RUTA_MAESTRO)]


# ---------- Listas cerradas de valores (enums) ----------
# `StrEnum`: cada opción es también un texto, así que `Pais.COLOMBIA == "CO"` es True
# y se escribe en JSON como "CO". Un valor fuera de la lista ("excel") es un error.


class Pais(StrEnum):
    COLOMBIA = "CO"
    ECUADOR = "EC"
    PERU = "PE"
    PANAMA = "PA"
    HONDURAS = "HN"


# Nombre de cada país, para mostrarlo y para que se pueda buscar "Ecuador" además de "EC".
NOMBRES_PAIS: dict[Pais, str] = {
    Pais.COLOMBIA: "Colombia",
    Pais.ECUADOR: "Ecuador",
    Pais.PERU: "Perú",
    Pais.PANAMA: "Panamá",
    Pais.HONDURAS: "Honduras",
}


class Formato(StrEnum):
    """Formato en el que el cliente espera el formulario."""

    EXCEL = "xlsx"
    PDF = "pdf"
    PORTAL = "portal"  # no se automatiza en el MVP: se generan valores para copiar


class TipoSoporte(StrEnum):
    """Documentos que un cliente puede exigir y que la empresa tiene (o no) en su repositorio."""

    CAMARA_COMERCIO = "camara_comercio"
    RUT = "rut"
    CERTIFICACION_BANCARIA = "certificacion_bancaria"
    PARAFISCALES = "parafiscales"
    ESTADOS_FINANCIEROS = "estados_financieros"
    CERTIFICADO_ISO_9001 = "certificado_iso_9001"
    # Lo exige el caso de Ecuador y no está en el repositorio: el checklist (Paso 8)
    # lo marcará como ausente. Debe estar aquí para que el tipo sea válido.
    CERTIFICADO_CUMPLIMIENTO_TRIBUTARIO = "certificado_cumplimiento_tributario"


# Nombre de cada soporte para personas (checklist y correo), en lugar del código.
NOMBRES_SOPORTE: dict[TipoSoporte, str] = {
    TipoSoporte.CAMARA_COMERCIO: "Cámara de Comercio",
    TipoSoporte.RUT: "RUT",
    TipoSoporte.CERTIFICACION_BANCARIA: "Certificación bancaria",
    TipoSoporte.PARAFISCALES: "Certificación de parafiscales",
    TipoSoporte.ESTADOS_FINANCIEROS: "Estados financieros",
    TipoSoporte.CERTIFICADO_ISO_9001: "Certificado ISO 9001",
    TipoSoporte.CERTIFICADO_CUMPLIMIENTO_TRIBUTARIO: "Certificado de cumplimiento tributario",
}


# ---------- Bases de los modelos ----------


class ModeloEstricto(BaseModel):
    # extra="forbid": un campo desconocido es un error.
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModeloTolerante(BaseModel):
    # extra="allow": un campo desconocido se acepta y queda en `model_extra`.
    model_config = ConfigDict(extra="allow", frozen=True)


# ---------- Archivos de un caso: datos/casos/<caso>/ ----------


class Solicitud(ModeloEstricto):
    """`solicitud.json`: el correo del cliente, ya normalizado."""

    id: IdCaso  # debe ser igual al nombre de la carpeta (lo revisa `validacion.py`)
    de: TextoNoVacio
    para: TextoNoVacio | None = None  # opcional: los datos lo traen, el diseño no lo usa
    asunto: TextoNoVacio
    fecha: date
    pais: Pais
    cliente: TextoNoVacio
    formato: Formato
    # El cuerpo del correo es contenido externo: más adelante se trata como DATO,
    # nunca como instrucción para el modelo (principio 5). Puede estar vacío.
    cuerpo: str
    # `default_factory=list` crea una lista nueva para cada solicitud. (Escribir
    # `= []` haría que todas compartieran la misma lista.)
    adjuntos: list[TextoNoVacio] = Field(default_factory=list)


class CeldaPlantilla(ModeloEstricto):
    """Un elemento de `plantilla-celdas.json` (formato Excel).

    Indica en qué celda va la etiqueta y en cuál el valor. Por ejemplo,
    "Razón social" en B3 y su valor en C3, en la hoja "Datos Proveedor".
    """

    hoja: NombreHoja
    celda_etiqueta: Celda
    etiqueta: TextoNoVacio
    celda_valor: Celda


class CampoPlantilla(ModeloEstricto):
    """Un elemento de `plantilla-campos.json` (formato PDF o portal). El orden importa."""

    etiqueta: TextoNoVacio
    # true o false en el JSON. Pydantic también acepta 1/0 y "true"/"false",
    # pero un texto como "si" se rechaza.
    obligatorio: bool


# ---------- Repositorio: datos/repositorio/ ----------


class Soporte(ModeloEstricto):
    """Un elemento de `soportes/index.json`: un documento que la empresa tiene."""

    tipo: TipoSoporte
    archivo: NombreArchivo  # nombre del archivo dentro de `soportes/`, sin carpetas
    # null = el documento no vence (por ejemplo, el RUT). Se compara con la fecha
    # de ejecución en el Paso 6 para saber si está vencido o "por vencer".
    vigencia_hasta: date | None
    pais_emisor: Pais
    descripcion: TextoNoVacio


# Submodelos del maestro: grupos de datos que en el JSON son objetos anidados.
# Todos sus campos son opcionales, por la misma razón que en `Maestro` (ver abajo).


class RepresentanteLegal(ModeloTolerante):
    nombre: TextoNoVacio | None = None
    tipo_identificacion: TextoNoVacio | None = None
    identificacion: TextoNoVacio | None = None  # dato sensible: se enmascara (Paso 3)
    cargo: TextoNoVacio | None = None
    email: TextoNoVacio | None = None


class Contacto(ModeloTolerante):
    """Se usa para el contacto comercial y para el financiero."""

    nombre: TextoNoVacio | None = None
    cargo: TextoNoVacio | None = None
    email: TextoNoVacio | None = None
    telefono: TextoNoVacio | None = None


class Banco(ModeloTolerante):
    nombre: TextoNoVacio | None = None
    tipo_cuenta: TextoNoVacio | None = None
    numero_cuenta: TextoNoVacio | None = None  # dato sensible: se enmascara (Paso 3)
    titular: TextoNoVacio | None = None
    swift: TextoNoVacio | None = None
    moneda: TextoNoVacio | None = None


class Ingresos(ModeloTolerante):
    # `Decimal` en vez de `float` para dinero: `float` puede redondear cifras grandes
    # o con centavos (0.1 + 0.2 = 0.30000000000000004). `Decimal` es exacto.
    valor: Decimal | None = None
    moneda: TextoNoVacio | None = None
    ano: int | None = None


class Maestro(ModeloTolerante):
    """`maestro.json`: los datos de la empresa, que alimentan todos los formularios.

    Solo `razon_social` y `nit` son obligatorios: sin ellos no hay nada que registrar.
    Los demás son opcionales (`| None = None`) a propósito: si un dato falta, el campo
    del formulario queda `faltante` y la validación lo sugiere al dueño del dato.
    Nunca se inventa un valor (principio 2).

    Los números que son identificadores (NIT, CIIU, código postal, cuenta) son texto,
    no `int`: pueden tener ceros a la izquierda ("050021") que un número perdería.
    """

    # Recomendados para la trazabilidad (HU-7): cada paquete registrará con qué
    # versión del maestro se generó. Los datos de ejemplo no los tienen.
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


# `glosario-campos.json`: cómo llama el cliente a un campo → dónde está en el maestro.
# Ejemplo: "Nombre de la empresa" → "razon_social", "SWIFT" → "banco.swift".
# No es una clase porque el archivo es un diccionario simple; `lectura.py` lo valida
# con un `TypeAdapter`.
Glosario = dict[TextoNoVacio, RutaMaestro]
