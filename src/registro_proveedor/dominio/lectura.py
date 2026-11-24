"""Lectura de los insumos de `datos/` y traducción de sus errores a mensajes claros.

¿Qué hace?
    Cada función `cargar_*` lee un archivo JSON, lo pasa por su modelo de Pydantic
    (`modelos.py`) y devuelve el dato ya validado. Por ejemplo, `cargar_solicitud`
    devuelve una `Solicitud` en la que `fecha` ya es una fecha y `formato` ya es
    uno de los tres valores válidos.

¿Qué pasa si algo está mal?
    Se lanza `ErrorDeDatos`, que lleva el archivo y la lista de problemas en español,
    por ejemplo: `elemento 3 > «celda_valor»: el valor «C0» no es válido; se espera
    una celda de Excel como «B3»`. Pydantic da sus errores en inglés y en un formato
    técnico; `_traducir` los convierte en frases para personas.

¿Por qué aquí sí se lanza una excepción, si "las herramientas nunca lanzan"?
    Porque esto es el dominio, no una herramienta. La capa de herramientas (Paso 3)
    capturará `ErrorDeDatos` y lo convertirá en `Resultado(ok=False, error=...)`, de
    modo que el agente nunca reciba una excepción. `validacion.py` también la captura,
    para anotarla en el reporte y seguir revisando lo demás.

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

# ---------- Nombres de archivos y carpetas ----------
# Están en un solo lugar para que, si un nombre cambia, se cambie solo aquí.
# Las rutas son relativas: a la carpeta del caso (las del caso) o a `datos/` (las demás).

CARPETA_CASOS = "casos"
ARCHIVO_SOLICITUD = "solicitud.json"
ARCHIVO_PLANTILLA_CELDAS = "plantilla-celdas.json"
ARCHIVO_PLANTILLA_CAMPOS = "plantilla-campos.json"
ARCHIVO_SOPORTES_EXIGIDOS = "soportes-exigidos.json"
ARCHIVO_MAESTRO = Path("repositorio") / "maestro.json"
CARPETA_SOPORTES = Path("repositorio") / "soportes"
ARCHIVO_INDICE_SOPORTES = CARPETA_SOPORTES / "index.json"
ARCHIVO_GLOSARIO = Path("glosario-campos.json")

# Pista que acompaña al error cuando un texto no cumple su patrón. Sin esto, la
# persona vería la expresión regular (`^[A-Z]{1,3}[1-9][0-9]*$`), que no le dice nada.
PISTAS_PATRON = {
    PATRON_ID_CASO: "solo minúsculas, números y guiones, como «co-industrias-delta»",
    PATRON_CELDA: "una celda de Excel como «B3» (letras mayúsculas y número desde 1)",
    PATRON_HOJA: "un nombre de hoja sin los caracteres [ ] : * ? / \\",
    PATRON_ARCHIVO: "un nombre de archivo sin carpetas, como «rut-2026.txt»",
    PATRON_RUTA_MAESTRO: "una ruta del maestro como «banco.swift» (minúsculas y puntos)",
}


class ErrorDeDatos(Exception):
    """Un archivo de `datos/` no se pudo leer o no cumple su modelo.

    `problemas` es una lista porque un mismo archivo puede tener varios errores a la
    vez (por ejemplo, falta un campo y otro tiene un valor inválido). Así se muestran
    todos juntos y no hay que corregir y volver a ejecutar uno por uno.
    """

    def __init__(self, archivo: Path, problemas: list[str]) -> None:
        super().__init__(f"{archivo}: " + "; ".join(problemas))
        self.archivo = archivo
        self.problemas = problemas


# ---------- Adaptadores de Pydantic ----------
# Un modelo (`class Solicitud(BaseModel)`) valida un objeto JSON. Pero varios archivos
# son una LISTA de objetos (`[{...}, {...}]`) o un diccionario simple. Para esos,
# Pydantic ofrece `TypeAdapter`: valida cualquier tipo, por ejemplo `list[Soporte]`.
# `Field(min_length=1)` exige que la lista no esté vacía: una plantilla sin campos
# no tiene sentido.
# Se crean una sola vez, al importar el módulo, porque construirlos tiene un costo.

_SOLICITUD = TypeAdapter(Solicitud)
_CELDAS = TypeAdapter(Annotated[list[CeldaPlantilla], Field(min_length=1)])
_CAMPOS = TypeAdapter(Annotated[list[CampoPlantilla], Field(min_length=1)])
_SOPORTES_EXIGIDOS = TypeAdapter(list[TipoSoporte])
_MAESTRO = TypeAdapter(Maestro)
_INDICE_SOPORTES = TypeAdapter(list[Soporte])
_GLOSARIO = TypeAdapter(Annotated[Glosario, Field(min_length=1)])


# ---------- Funciones públicas ----------


def carpeta_de_caso(datos: Path, caso: str) -> Path:
    """Devuelve la carpeta de un caso, comprobando que el nombre sea válido y que exista.

    Protege contra *path traversal*: si alguien (o el modelo de lenguaje, más
    adelante) pide el caso `../repositorio`, la ruta saldría de `datos/casos/`.
    Hay dos barreras:
    1. el nombre debe cumplir `PATRON_ID_CASO`, que no admite "." ni "/";
    2. aunque pasara, la ruta final se resuelve y se comprueba que siga dentro
       de `datos/casos/`. Es una defensa doble a propósito.
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


# Las funciones `cargar_*` son todas iguales por dentro: arman la ruta del archivo
# y llaman a `_validar` con el adaptador que corresponde.


def cargar_solicitud(carpeta_caso: Path) -> Solicitud:
    return _validar(carpeta_caso / ARCHIVO_SOLICITUD, _SOLICITUD)


def cargar_plantilla_celdas(carpeta_caso: Path) -> list[CeldaPlantilla]:
    return _validar(carpeta_caso / ARCHIVO_PLANTILLA_CELDAS, _CELDAS)


def cargar_plantilla_campos(carpeta_caso: Path) -> list[CampoPlantilla]:
    return _validar(carpeta_caso / ARCHIVO_PLANTILLA_CAMPOS, _CAMPOS)


def cargar_soportes_exigidos(carpeta_caso: Path) -> list[TipoSoporte]:
    return _validar(carpeta_caso / ARCHIVO_SOPORTES_EXIGIDOS, _SOPORTES_EXIGIDOS)


def cargar_maestro(datos: Path) -> Maestro:
    return _validar(datos / ARCHIVO_MAESTRO, _MAESTRO)


def cargar_indice_soportes(datos: Path) -> list[Soporte]:
    return _validar(datos / ARCHIVO_INDICE_SOPORTES, _INDICE_SOPORTES)


def cargar_glosario(datos: Path) -> Glosario:
    return _validar(datos / ARCHIVO_GLOSARIO, _GLOSARIO)


def leer_json(ruta: Path) -> object:
    """Lee un archivo JSON y devuelve su contenido sin validar.

    Detecta, con un mensaje claro, los problemas del archivo en sí (antes de mirar
    su contenido): que no exista, que no esté en UTF-8, que el JSON esté mal escrito
    o que tenga claves repetidas.

    Devuelve `object` porque un JSON puede ser cualquier cosa (lista, diccionario,
    texto...). Quien lo usa lo valida después con su modelo.
    """
    try:
        # "utf-8-sig" acepta UTF-8 con o sin BOM (una marca invisible que algunos
        # editores de Windows ponen al inicio del archivo y que rompería `json`).
        texto = ruta.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        # `from None` oculta la excepción original: la persona solo ve nuestro mensaje,
        # sin la traza técnica de Python.
        raise ErrorDeDatos(ruta, ["no existe el archivo"]) from None
    except UnicodeDecodeError:
        raise ErrorDeDatos(ruta, ["el archivo no está en UTF-8"]) from None
    try:
        # `object_pairs_hook` le da a `json` una función propia para armar cada objeto.
        # La usamos para detectar claves repetidas: por defecto, si un JSON tiene
        # "NIT" dos veces, `json` se queda con la última sin avisar. En el glosario
        # eso escondería un error.
        return json.loads(texto, object_pairs_hook=_sin_claves_repetidas)
    except json.JSONDecodeError as e:
        raise ErrorDeDatos(
            ruta, [f"no es un JSON válido (línea {e.lineno}, columna {e.colno})"]
        ) from None
    except _ClaveRepetida as e:
        raise ErrorDeDatos(ruta, [str(e)]) from None


# ---------- Detalles internos ----------
# Las funciones que empiezan con "_" son internas de este módulo: no se usan desde fuera.


class _ClaveRepetida(ValueError):
    """Excepción interna para salir de `json.loads` cuando se encuentra una clave repetida."""


def _sin_claves_repetidas(pares: list[tuple[str, object]]) -> dict[str, object]:
    """Arma un diccionario a partir de pares (clave, valor), fallando si una clave se repite."""
    resultado: dict[str, object] = {}
    for clave, valor in pares:
        if clave in resultado:
            raise _ClaveRepetida(f"la clave «{clave}» está repetida")
        resultado[clave] = valor
    return resultado


def _validar[T](ruta: Path, adaptador: TypeAdapter[T]) -> T:
    """Lee el JSON y lo valida con el adaptador. Si falla, lanza `ErrorDeDatos`.

    `[T]` hace que la función sea genérica: si el adaptador es de `Solicitud`, el
    resultado es una `Solicitud`. Así mypy sabe el tipo exacto de lo que devuelve.
    """
    contenido = leer_json(ruta)
    try:
        return adaptador.validate_python(contenido)
    except ValidationError as e:
        # `e.errors()` trae TODOS los problemas encontrados, no solo el primero.
        raise ErrorDeDatos(ruta, [describir_error_validacion(err) for err in e.errors()]) from None


def describir_error_validacion(err: ErrorDetails) -> str:
    """Convierte un error de Pydantic en una frase en español con su ubicación.

    Es pública (sin "_") porque también la usan las herramientas (Paso 3) para
    explicar por qué los argumentos que pidió el modelo no son válidos.
    """
    ubicacion = _ubicacion(err["loc"])
    mensaje = _traducir(err)
    return f"{ubicacion}: {mensaje}" if ubicacion else mensaje


def _ubicacion(loc: tuple[int | str, ...]) -> str:
    """Convierte la ubicación de Pydantic en texto legible.

    Pydantic indica dónde está el error con una tupla, como `(2, "celda_valor")`:
    el número es la posición en una lista (empieza en 0) y el texto es el nombre
    del campo. Aquí se vuelve "elemento 3 > «celda_valor»": se suma 1 porque las
    personas cuentan desde 1.
    """
    partes = [f"elemento {p + 1}" if isinstance(p, int) else f"«{p}»" for p in loc]
    return " > ".join(partes)


def _traducir(err: ErrorDetails) -> str:
    """Traduce al español los tipos de error de Pydantic más comunes.

    `err["type"]` es un código fijo de Pydantic ("missing", "enum", ...).
    `err["input"]` es el valor que llegó y `err["ctx"]` trae datos extra, como los
    valores esperados o el patrón. Si aparece un tipo que no está en la tabla, se
    devuelve el mensaje original de Pydantic (en inglés) para no perder información.
    """
    tipo = err["type"]
    valor = err.get("input")
    ctx = err.get("ctx", {})
    if tipo == "missing":
        return "falta este campo obligatorio"
    if tipo == "extra_forbidden":
        return "campo no reconocido (¿está mal escrito?)"
    if tipo in ("enum", "literal_error"):
        # Pydantic escribe "'xlsx', 'pdf' or 'portal'": se cambia "or" por "o".
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
    # Los siguientes usan `startswith` porque Pydantic tiene varias variantes de cada
    # uno (por ejemplo, "date_parsing", "date_from_datetime_parsing", "date_type").
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
