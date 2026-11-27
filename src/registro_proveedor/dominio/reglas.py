"""Reglas de negocio configurables (`config/reglas.yaml`) y las reglas de vigencia.

¿Por qué en un archivo aparte?
    Hay valores que el negocio puede querer cambiar sin pedirle nada a un
    programador: cuántos días antes avisar que un documento vence, qué tan parecida
    debe ser una etiqueta para llenarla sola, cómo se llama el identificador
    tributario en cada país. Esos valores viven en `config/reglas.yaml`. Aquí se leen,
    se validan (con Pydantic, igual que los datos) y se aplican.

Qué hay en este módulo:
    - Los modelos del YAML y `cargar_reglas`.
    - RN1: `nota_identificador_extranjero` (la aplica el mapeo, en `mapeo.py`).
    - RN2: `es_dato_bancario` (la usará el paquete del Paso 8).
    - RN3 y RN6: `evaluar_soportes` y `bloquean_firma` (las usará el checklist del Paso 8).

La lista de datos SENSIBLES (RN8) no está aquí a propósito: es una regla de
seguridad, no de negocio, y vive en el código (`observabilidad.py`). Así, un error
al editar el YAML no puede dejar expuesto un número de cuenta.
"""

from datetime import date
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from registro_proveedor.dominio.lectura import ErrorDeDatos, describir_error_validacion
from registro_proveedor.dominio.modelos import (
    NOMBRES_PAIS,
    Pais,
    RutaMaestro,
    Soporte,
    TextoNoVacio,
    TipoSoporte,
)


class _Modelo(BaseModel):
    # extra="forbid": una clave mal escrita en el YAML (`umbral_llenno`) es un error,
    # en vez de ignorarse y dejar la regla con su valor anterior sin que nadie lo note.
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------- Modelos del YAML ----------


class ReglasMapeo(_Modelo):
    # Números entre 0 y 1 (`ge` = mayor o igual, `le` = menor o igual).
    umbral_lleno: float = Field(ge=0, le=1)
    umbral_confirmar: float = Field(ge=0, le=1)
    confianza_normalizado: float = Field(ge=0, le=1)
    # Paso 21 (piloto): rutas del maestro que nunca se proponen por parecido, y palabras
    # que hacen que una etiqueta se trate como identificador. Ver config/reglas.yaml.
    datos_sin_parecido: list[str] = Field(default_factory=list)
    palabras_de_identificador: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _orden_de_umbrales(self) -> "ReglasMapeo":
        if self.umbral_confirmar > self.umbral_lleno:
            raise ValueError(
                "umbral_confirmar no puede ser mayor que umbral_lleno "
                f"({self.umbral_confirmar} > {self.umbral_lleno})"
            )
        return self


class ReglaIdentificador(_Modelo):
    """RN1: cómo se llama el identificador tributario en cada país."""

    ruta_maestro: RutaMaestro
    pais_empresa: Pais
    por_pais: dict[Pais, TextoNoVacio]

    @model_validator(mode="after")
    def _todos_los_paises(self) -> "ReglaIdentificador":
        faltan = [p.value for p in Pais if p not in self.por_pais]
        if faltan:
            raise ValueError(f"por_pais no tiene el identificador de: {', '.join(faltan)}")
        return self


class ReglaBancaria(_Modelo):
    """RN2: qué rutas del maestro son datos bancarios."""

    rutas: list[RutaMaestro] = Field(min_length=1)


class ReglaVigencias(_Modelo):
    """RN3 y RN6: desde cuántos días antes de vencer se avisa."""

    dias_por_vencer: int = Field(ge=0, le=365)


class Reglas(_Modelo):
    mapeo: ReglasMapeo
    identificador_tributario: ReglaIdentificador
    datos_bancarios: ReglaBancaria
    vigencias: ReglaVigencias


def cargar_reglas(ruta: Path) -> Reglas:
    """Lee y valida `reglas.yaml`. Lanza `ErrorDeDatos` con mensajes claros si algo está mal."""
    try:
        texto = ruta.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ErrorDeDatos(ruta, ["no existe el archivo de reglas"]) from None
    try:
        # `safe_load` solo crea datos simples (textos, números, listas, diccionarios).
        # `yaml.load` sin "safe" podría ejecutar código escrito en el archivo.
        contenido = yaml.safe_load(texto)
    except yaml.YAMLError as e:
        marca = getattr(e, "problem_mark", None)
        donde = f" (línea {marca.line + 1}, columna {marca.column + 1})" if marca else ""
        raise ErrorDeDatos(ruta, [f"no es un YAML válido{donde}"]) from None
    try:
        return Reglas.model_validate(contenido)
    except ValidationError as e:
        raise ErrorDeDatos(ruta, [describir_error_validacion(err) for err in e.errors()]) from None


# ---------- RN1 · Identificador extranjero ----------


def nota_identificador_extranjero(regla: ReglaIdentificador, pais_cliente: Pais) -> str | None:
    """La nota de RN1 si el cliente es de otro país; None si es del país de la empresa.

    Ejemplo: "identificador extranjero: el cliente de Ecuador pide RUC; la empresa solo
    tiene NIT de Colombia: confirme si se acepta".
    """
    if pais_cliente is regla.pais_empresa:
        return None
    return (
        f"identificador extranjero: el cliente de {NOMBRES_PAIS[pais_cliente]} pide "
        f"{regla.por_pais[pais_cliente]}; la empresa solo tiene "
        f"{regla.por_pais[regla.pais_empresa]} de {NOMBRES_PAIS[regla.pais_empresa]}: "
        "confirme si se acepta"
    )


# ---------- RN2 · Datos bancarios ----------


def es_dato_bancario(ruta: str, regla: ReglaBancaria) -> bool:
    return ruta in regla.rutas


# ---------- RN3 y RN6 · Vigencia de los soportes ----------


class EstadoSoporte(StrEnum):
    PRESENTE = "presente"  # existe y está vigente (o no vence)
    POR_VENCER = "por_vencer"  # existe, pero vence pronto: se avisa, no bloquea (RN6)
    VENCIDO = "vencido"  # existe, pero ya venció: bloquea (RN3)
    AUSENTE = "ausente"  # el cliente lo exige y la empresa no lo tiene: bloquea (RN3)


ESTADOS_QUE_BLOQUEAN = frozenset({EstadoSoporte.VENCIDO, EstadoSoporte.AUSENTE})


class EvaluacionSoporte(_Modelo):
    """Cómo está un soporte exigido, a la fecha de ejecución."""

    tipo: TipoSoporte
    estado: EstadoSoporte
    archivo: str | None  # None si está ausente
    vigencia_hasta: date | None
    dias_restantes: int | None  # negativo si ya venció; None si no vence o está ausente
    bloquea: bool
    nota: str


def evaluar_soporte(
    tipo: TipoSoporte, indice: list[Soporte], fecha: date, regla: ReglaVigencias
) -> EvaluacionSoporte:
    """Califica UN soporte exigido comparando su `vigencia_hasta` con la fecha de ejecución.

    Un documento que vence HOY todavía es válido hoy (0 días restantes → por vencer).
    Vence el día siguiente.
    """
    soporte = next((s for s in indice if s.tipo is tipo), None)
    if soporte is None:
        return _evaluacion(tipo, None, None, EstadoSoporte.AUSENTE, "no está en el repositorio")
    if soporte.vigencia_hasta is None:
        return _evaluacion(tipo, soporte, None, EstadoSoporte.PRESENTE, "no tiene vencimiento")
    dias = (soporte.vigencia_hasta - fecha).days
    vence = soporte.vigencia_hasta.isoformat()
    if dias < 0:
        estado, nota = EstadoSoporte.VENCIDO, f"venció el {vence} (hace {_dias(-dias)})"
    elif dias <= regla.dias_por_vencer:
        estado = EstadoSoporte.POR_VENCER
        nota = f"vence el {vence}: quedan {_dias(dias)} (aviso desde {regla.dias_por_vencer})"
    else:
        estado, nota = EstadoSoporte.PRESENTE, f"vigente hasta el {vence} ({_dias(dias)})"
    return _evaluacion(tipo, soporte, dias, estado, nota)


def _dias(n: int) -> str:
    """La cantidad con "día" en singular o plural: "1 día", "29 días"."""
    return f"{n} día" if n == 1 else f"{n} días"


def _evaluacion(
    tipo: TipoSoporte,
    soporte: Soporte | None,
    dias: int | None,
    estado: EstadoSoporte,
    nota: str,
) -> EvaluacionSoporte:
    return EvaluacionSoporte(
        tipo=tipo,
        estado=estado,
        archivo=soporte.archivo if soporte else None,
        vigencia_hasta=soporte.vigencia_hasta if soporte else None,
        dias_restantes=dias,
        bloquea=estado in ESTADOS_QUE_BLOQUEAN,
        nota=nota,
    )


def evaluar_soportes(
    exigidos: list[TipoSoporte], indice: list[Soporte], fecha: date, regla: ReglaVigencias
) -> list[EvaluacionSoporte]:
    """Califica todos los soportes que exige el cliente, en el mismo orden."""
    return [evaluar_soporte(tipo, indice, fecha, regla) for tipo in exigidos]


def bloquean_firma(evaluaciones: list[EvaluacionSoporte]) -> bool:
    """RN3: True si algún soporte está vencido o ausente.

    Un campo faltante del formulario NO bloquea (también RN3): se avisa en el
    checklist, pero el paquete puede ir a firma.
    """
    return any(e.bloquea for e in evaluaciones)
