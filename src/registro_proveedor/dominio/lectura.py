"""Lectura de los insumos de `datos/` y traducción de sus errores a mensajes claros.

Cada función `cargar_*` devuelve el modelo ya validado o lanza `ErrorDeDatos` con
la lista de problemas en español. La capa de herramientas (Paso 3) convertirá esa
excepción en `Resultado(ok=False, ...)`; aquí, dentro del dominio, sí se lanza.

Este módulo solo **lee**: nunca escribe en `datos/`.
"""

import json
import re
from pathlib import Path
from typing import Annotated

from pydantic import Field, TypeAdapter, ValidationError
from pydantic_core import ErrorDetails

from registro_proveedor.dominio.modelos import (
    PATRON_ARCHIVO,
    PATRON_CELDA,
    PATRON_HOJA,
    PATRON_ID_CASO,
    PATRON_RUTA_MAESTRO,
    CampoPlantilla,
    CeldaPlantilla,
    Glosario,
    Maestro,
    Solicitud,
    Soporte,
    TipoSoporte,
)

# ---------- Nombres de archivos y carpetas (un solo lugar) ----------

CARPETA_CASOS = "casos"
ARCHIVO_SOLICITUD = "solicitud.json"
ARCHIVO_PLANTILLA_CELDAS = "plantilla-celdas.json"
ARCHIVO_PLANTILLA_CAMPOS = "plantilla-campos.json"
ARCHIVO_SOPORTES_EXIGIDOS = "soportes-exigidos.json"
ARCHIVO_MAESTRO = Path("repositorio") / "maestro.json"
CARPETA_SOPORTES = Path("repositorio") / "soportes"
ARCHIVO_INDICE_SOPORTES = CARPETA_SOPORTES / "index.json"
ARCHIVO_GLOSARIO = Path("glosario-campos.json")

# Pista que acompaña al error cuando un texto no cumple su patrón.
PISTAS_PATRON = {
    PATRON_ID_CASO: "solo minúsculas, números y guiones, como «co-industrias-delta»",
    PATRON_CELDA: "una celda de Excel como «B3» (letras mayúsculas y número desde 1)",
    PATRON_HOJA: "un nombre de hoja sin los caracteres [ ] : * ? / \\",
    PATRON_ARCHIVO: "un nombre de archivo sin carpetas, como «rut-2026.txt»",
    PATRON_RUTA_MAESTRO: "una ruta del maestro como «banco.swift» (minúsculas y puntos)",
}


class ErrorDeDatos(Exception):
    """Un archivo de `datos/` no se pudo leer o no cumple su modelo."""

    def __init__(self, archivo: Path, problemas: list[str]) -> None:
        super().__init__(f"{archivo}: " + "; ".join(problemas))
        self.archivo = archivo
        self.problemas = problemas


# ---------- Adaptadores de Pydantic para los archivos que son listas o diccionarios ----------

_CELDAS = TypeAdapter(Annotated[list[CeldaPlantilla], Field(min_length=1)])
_CAMPOS = TypeAdapter(Annotated[list[CampoPlantilla], Field(min_length=1)])
_SOPORTES_EXIGIDOS = TypeAdapter(list[TipoSoporte])
_INDICE_SOPORTES = TypeAdapter(list[Soporte])
_GLOSARIO = TypeAdapter(Annotated[Glosario, Field(min_length=1)])


# ---------- Funciones públicas ----------


def carpeta_de_caso(datos: Path, caso: str) -> Path:
    """Devuelve la carpeta de un caso, comprobando que el nombre sea válido y que exista.

    Protege contra rutas como `../secreto`: el nombre debe cumplir el patrón y la
    ruta resultante debe quedar dentro de `datos/casos/`.
    """
    casos = (datos / CARPETA_CASOS).resolve()
    if not re.fullmatch(PATRON_ID_CASO, caso):
        raise ErrorDeDatos(
            datos / CARPETA_CASOS,
            [f"el nombre de caso «{caso}» no es válido; se espera {PISTAS_PATRON[PATRON_ID_CASO]}"],
        )
    carpeta = (casos / caso).resolve()
    if not carpeta.is_relative_to(casos) or not carpeta.is_dir():
        raise ErrorDeDatos(datos / CARPETA_CASOS, [f"no existe el caso «{caso}»"])
    return carpeta


def cargar_solicitud(carpeta_caso: Path) -> Solicitud:
    ruta = carpeta_caso / ARCHIVO_SOLICITUD
    return _validar(ruta, TypeAdapter(Solicitud))


def cargar_plantilla_celdas(carpeta_caso: Path) -> list[CeldaPlantilla]:
    return _validar(carpeta_caso / ARCHIVO_PLANTILLA_CELDAS, _CELDAS)


def cargar_plantilla_campos(carpeta_caso: Path) -> list[CampoPlantilla]:
    return _validar(carpeta_caso / ARCHIVO_PLANTILLA_CAMPOS, _CAMPOS)


def cargar_soportes_exigidos(carpeta_caso: Path) -> list[TipoSoporte]:
    return _validar(carpeta_caso / ARCHIVO_SOPORTES_EXIGIDOS, _SOPORTES_EXIGIDOS)


def cargar_maestro(datos: Path) -> Maestro:
    return _validar(datos / ARCHIVO_MAESTRO, TypeAdapter(Maestro))


def cargar_indice_soportes(datos: Path) -> list[Soporte]:
    return _validar(datos / ARCHIVO_INDICE_SOPORTES, _INDICE_SOPORTES)


def cargar_glosario(datos: Path) -> Glosario:
    return _validar(datos / ARCHIVO_GLOSARIO, _GLOSARIO)


def leer_json(ruta: Path) -> object:
    """Lee un JSON en UTF-8 y rechaza las claves repetidas (que `json` ignoraría en silencio)."""
    try:
        texto = ruta.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ErrorDeDatos(ruta, ["no existe el archivo"]) from None
    except UnicodeDecodeError:
        raise ErrorDeDatos(ruta, ["el archivo no está en UTF-8"]) from None
    try:
        return json.loads(texto, object_pairs_hook=_sin_claves_repetidas)
    except json.JSONDecodeError as e:
        raise ErrorDeDatos(
            ruta, [f"no es un JSON válido (línea {e.lineno}, columna {e.colno})"]
        ) from None
    except _ClaveRepetida as e:
        raise ErrorDeDatos(ruta, [str(e)]) from None


# ---------- Detalles internos ----------


class _ClaveRepetida(ValueError):
    pass


def _sin_claves_repetidas(pares: list[tuple[str, object]]) -> dict[str, object]:
    resultado: dict[str, object] = {}
    for clave, valor in pares:
        if clave in resultado:
            raise _ClaveRepetida(f"la clave «{clave}» está repetida")
        resultado[clave] = valor
    return resultado


def _validar[T](ruta: Path, adaptador: TypeAdapter[T]) -> T:
    contenido = leer_json(ruta)
    try:
        return adaptador.validate_python(contenido)
    except ValidationError as e:
        raise ErrorDeDatos(ruta, [_describir(err) for err in e.errors()]) from None


def _describir(err: ErrorDetails) -> str:
    """Convierte un error de Pydantic en una frase en español con su ubicación."""
    ubicacion = _ubicacion(err["loc"])
    mensaje = _traducir(err)
    return f"{ubicacion}: {mensaje}" if ubicacion else mensaje


def _ubicacion(loc: tuple[int | str, ...]) -> str:
    partes = [f"elemento {p + 1}" if isinstance(p, int) else f"«{p}»" for p in loc]
    return " > ".join(partes)


def _traducir(err: ErrorDetails) -> str:
    """Tabla de traducciones de los tipos de error de Pydantic más comunes."""
    tipo = err["type"]
    valor = err.get("input")
    ctx = err.get("ctx", {})
    if tipo == "missing":
        return "falta este campo obligatorio"
    if tipo == "extra_forbidden":
        return "campo no reconocido (¿está mal escrito?)"
    if tipo in ("enum", "literal_error"):
        esperado = str(ctx.get("expected", "")).replace(" or ", " o ")
        return f"el valor «{valor}» no es válido; se espera uno de: {esperado}"
    if tipo == "string_pattern_mismatch":
        pista = PISTAS_PATRON.get(str(ctx.get("pattern")), "el formato esperado")
        return f"el valor «{valor}» no es válido; se espera {pista}"
    if tipo == "string_too_short":
        return "no puede estar vacío"
    if tipo == "string_too_long":
        return f"es demasiado largo (máximo {ctx.get('max_length')} caracteres)"
    if tipo == "too_short":
        return "la lista no puede estar vacía"
    if tipo.startswith("date"):
        return f"«{valor}» no es una fecha válida (formato AAAA-MM-DD)"
    if tipo == "string_type":
        return f"debe ser texto (entre comillas), no «{valor}»"
    if tipo.startswith("bool"):
        return "debe ser true o false"
    if tipo.startswith("int"):
        return f"debe ser un número entero, no «{valor}»"
    if tipo.startswith("decimal"):
        return f"debe ser un número, no «{valor}»"
    if tipo == "list_type":
        return "debe ser una lista [ ... ]"
    if tipo in ("dict_type", "model_type", "model_attributes_type"):
        return "debe ser un objeto { ... }"
    return err["msg"]
