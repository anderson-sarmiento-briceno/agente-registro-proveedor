"""Utilidades de texto: normalizar para comparar sin que importen mayúsculas, tildes ni signos.

¿Para qué?
    La analista (o el modelo) puede escribir "Panamá", "panama" o "PANAMÁ", y todos
    deben encontrar el mismo caso. Lo mismo con las etiquetas de los formularios en
    el Paso 5: "Razón social", "razon social" y "RAZÓN SOCIAL:" son la misma etiqueta.
    La solución es comparar las versiones "normalizadas" de los textos.
"""

import re
import unicodedata


def normalizar(texto: str) -> str:
    """Versión del texto en minúsculas, sin tildes y con los signos convertidos en espacios.

    Ejemplos:
        "Panamá"                   → "panama"
        "Razón social:"            → "razon social"
        "Departamento / Provincia" → "departamento provincia"
        "ec-corp-andina"           → "ec corp andina"

    Cómo quita las tildes: la forma Unicode "NFKD" separa cada letra de su tilde
    ("á" pasa a ser "a" + una marca de tilde aparte). Después se descartan esas marcas
    (`unicodedata.combining`). La "ñ" queda como "n", igual que en una búsqueda web.
    """
    separado = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in separado if not unicodedata.combining(c))
    # Todo lo que no sea letra o número (espacios, guiones, puntos, "/"...) se vuelve
    # un solo espacio; `strip` quita los espacios de los extremos.
    return re.sub(r"[^a-z0-9]+", " ", sin_tildes.lower()).strip()


def palabras(texto: str) -> list[str]:
    """Las palabras del texto ya normalizado: "Corporación Andina" → ["corporacion", "andina"]."""
    return normalizar(texto).split()
