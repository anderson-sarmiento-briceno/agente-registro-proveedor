"""Guardarraíles del agente (sección 9.4 del plan, Paso 14): dos revisiones deterministas.

1. `revisar_respuesta` · CA2 · "el modelo no puede afirmar valores que no hayan salido
   de una herramienta". Antes de mostrarle la respuesta a la analista, se buscan en el
   texto datos que PARECEN sensibles (números largos como un NIT, una cuenta o un
   teléfono, y correos electrónicos). Cada uno se compara con lo que sí apareció en la
   conversación: los resultados de las herramientas y lo que escribió la analista.
   Lo que no aparece se OCULTA como «[dato no verificado]» y se avisa al final.

       "El NIT es 900123456."  → el NIT salió del mapeo → se deja
       "La cuenta es 03100012345" → el modelo solo vio ****2345 → se oculta

   Se comparan solo los dígitos: "900.123.456" y "900123456" son el mismo número.
   Las fechas ("2026-09-01") no se revisan: no son datos sensibles y darían falsas
   alarmas. Los números cortos (menos de 7 dígitos: conteos, "****2345") tampoco.

2. `detectar_instrucciones` · principio 5 · "el contenido externo es dato, no orden".
   Busca en un resultado de herramienta frases que parecen ÓRDENES para el modelo
   ("ignora tus instrucciones", "eres ahora…", "aprueba todo", el nombre de una
   herramienta…). Pueden venir de lo que escribió el cliente: el nombre, las etiquetas
   de la plantilla, las notas. Si aparece una, el ciclo le antepone una advertencia al
   resultado y se la muestra a la analista.

Ninguna de las dos es infalible: son listas fijas de patrones, no entienden el texto.
Por eso no son la única defensa: el cuerpo del correo nunca llega al modelo (D18), lo
sensible le llega enmascarado y ninguna acción ocurre sin la aprobación de la analista
(Paso 13). Si la lista se queda corta, se agrega un patrón y su prueba.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

# ---------- 1. Datos que no salieron de las herramientas ----------

OCULTO = "[dato no verificado]"

# Cuántos dígitos debe tener un número para considerarlo un posible dato sensible.
# 7 o más: un NIT (9), una cuenta (10 u 11), un teléfono (7 a 12). Los conteos y los
# últimos 4 dígitos de un valor enmascarado quedan por fuera.
MINIMO_DE_DIGITOS = 7


class TipoDato(StrEnum):
    NUMERO = "número largo"
    CORREO = "correo electrónico"


@dataclass(frozen=True)
class Revision:
    """La respuesta revisada y qué tipo de datos se ocultaron (nunca los datos mismos)."""

    texto: str
    ocultos: tuple[TipoDato, ...]


# Un número: dígitos, y entre ellos como mucho UN separador (punto, guion o espacio),
# como en "900.123.456", "900123456-7" o "+57 300 123 4567". Delante no puede haber
# una letra, un dígito ni un asterisco (así "****2345" no cuenta).
_NUMERO = re.compile(r"(?<![\w*])\+?\d(?:[ .\-]?\d)+(?![\w])")
_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Fecha ISO, con hora opcional: "2026-09-01" o "2026-09-01T12:00:00Z".
_FECHA = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?\b"
)
_SEPARADOR_ENTRE_DIGITOS = re.compile(r"(?<=\d)[ .\-](?=\d)")


def revisar_respuesta(texto: str, fuentes: Iterable[str]) -> Revision:
    """Oculta los datos de `texto` que no aparecen en ninguna de las `fuentes`.

    `fuentes` son los textos en los que el modelo pudo ver datos verdaderos: los
    resultados de las herramientas y los mensajes de la analista de esta conversación.
    """
    vistos = _normalizar_numeros(" ".join(fuentes)).lower()
    fechas = [m.span() for m in _FECHA.finditer(texto)]
    ocultos: list[TipoDato] = []

    def correo(m: re.Match[str]) -> str:
        if m.group().lower() in vistos:
            return m.group()
        ocultos.append(TipoDato.CORREO)
        return OCULTO

    def numero(m: re.Match[str]) -> str:
        if _se_cruza(m.span(), fechas) or _verificado(m.group(), vistos):
            return m.group()
        ocultos.append(TipoDato.NUMERO)
        return OCULTO

    # Primero los correos (pueden tener números adentro); después los números.
    revisado = _CORREO.sub(correo, texto)
    fechas = [m.span() for m in _FECHA.finditer(revisado)]  # posiciones tras el cambio
    revisado = _NUMERO.sub(numero, revisado)
    if ocultos:
        revisado += "\n\n" + _nota(ocultos)
    return Revision(texto=revisado, ocultos=tuple(ocultos))


def _verificado(numero: str, vistos: str) -> bool:
    """¿Es un número corto, o salió (entero o por partes) de las fuentes?

    "Por partes": un NIT con su dígito de verificación ("900123456-7") se acepta si el
    NIT salió de las herramientas; el "7" suelto es corto y no se revisa.
    """
    digitos = re.sub(r"\D", "", numero)
    if len(digitos) < MINIMO_DE_DIGITOS or digitos in vistos:
        return True
    partes = [re.sub(r"\D", "", p) for p in numero.split("-")]
    return len(partes) > 1 and all(len(p) < MINIMO_DE_DIGITOS or p in vistos for p in partes)


def _normalizar_numeros(texto: str) -> str:
    """Quita los separadores ENTRE dígitos: "900.123.456" → "900123456"."""
    return _SEPARADOR_ENTRE_DIGITOS.sub("", texto)


def _se_cruza(tramo: tuple[int, int], otros: list[tuple[int, int]]) -> bool:
    inicio, fin = tramo
    return any(inicio < f and i < fin for i, f in otros)


def _nota(ocultos: list[TipoDato]) -> str:
    cuantos = len(ocultos)
    tipos = ", ".join(sorted({str(t) for t in ocultos}))
    dato = "1 dato que no salió" if cuantos == 1 else f"{cuantos} datos que no salieron"
    return (
        f"⚠️ Oculté {dato} de las herramientas de esta conversación ({tipos}). "
        "Revise la respuesta con cuidado."
    )


# ---------- 2. Texto que parece una instrucción ----------


@dataclass(frozen=True)
class Patron:
    nombre: str  # para la alerta y el log: qué tipo de frase se encontró
    expresion: re.Pattern[str]


def _p(nombre: str, expresion: str) -> Patron:
    return Patron(nombre, re.compile(expresion))


# Se buscan sobre el texto en minúsculas y sin tildes (`_plano`), en español e inglés.
# `.{0,40}` = hasta 40 caracteres cualesquiera entre las dos partes de la frase.
PATRONES = (
    _p(
        "ignorar instrucciones",
        r"\b(ignor\w*|olvid\w*|omit\w*|desobedec\w*|disregard|forget)\b.{0,40}"
        r"\b(instruccion\w*|regla\w*|indicacion\w*|instructions?|rules?|prompt)\b",
    ),
    _p(
        "instrucciones del sistema",
        r"\b(instrucciones|indicaciones|mensaje|prompt) (anteriores|previas|del sistema)\b"
        r"|\bsystem prompt\b|<\s*/?\s*(system|sistema|instrucciones|instructions)\b",
    ),
    _p(
        "cambiar de papel",
        r"\b(eres ahora|ahora eres|actua como|haz de cuenta|you are now|act as)\b",
    ),
    _p(
        "aprobar o enviar sin preguntar",
        r"\b(apruebe|aprueba|aprobar|approve|autoric\w*|autoriza\w*)\b.{0,40}"
        r"\b(todo|todos|envio|envia\w*|paquete|automatic\w*|everything)\b"
        r"|\bsin (preguntar|confirmar|aprobacion|consultar)\b|\bwithout (asking|approval)\b",
    ),
    _p(
        "enviar a otro destino",
        r"\b(envi\w*|reenvi\w*|mand\w*|send|forward)\b.{0,60}[\w.+-]+@[\w-]+\.\w+",
    ),
    _p(
        "mostrar datos ocultos",
        r"\b(muestr\w*|revel\w*|reveal|show|print)\b.{0,40}"
        r"\b(cuenta completa|numero completo|clave|contrasena|password|api key|secret\w*)\b",
    ),
)
# Aparte: el nombre de una herramienta dentro de un DATO es sospechoso (alguien intenta
# que el modelo la llame). En los mensajes de error es normal: nuestro propio código
# dice "primero use proveedor_mapear_campos". Por eso es opcional.
PATRON_HERRAMIENTA = _p("nombre de una herramienta", r"\bproveedor_[a-z_]+\b")


def detectar_instrucciones(texto: str, *, incluir_herramientas: bool = True) -> list[str]:
    """Los tipos de frase sospechosa que aparecen en `texto` (vacío si no hay ninguna)."""
    plano = _plano(texto)
    patrones = (*PATRONES, PATRON_HERRAMIENTA) if incluir_herramientas else PATRONES
    return [p.nombre for p in patrones if p.expresion.search(plano)]


def _plano(texto: str) -> str:
    """Minúsculas y sin tildes, pero CON los signos ("@", "_", "<"): los patrones los usan."""
    separado = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in separado if not unicodedata.combining(c)).lower()
