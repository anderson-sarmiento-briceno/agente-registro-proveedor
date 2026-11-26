"""Cuánto cuesta una llamada al modelo, en dólares (Paso 18).

Antes, el precio de claude-haiku-5-5 estaba fijo dentro de `prueba_real.py`: si alguien
cambiaba `LLM_MODELO`, el costo calculado seguía siendo el de haiku, y los topes de
dinero del Paso 18 quedarían mal. Ahora hay una tabla por modelo.

¿Y si el modelo no está en la tabla?
    Se usa un PRECIO DE RESGUARDO alto, a propósito. Para los topes es mejor pasarse
    (cortar antes) que quedarse corto (gastar de más sin darse cuenta). Nunca se cuenta
    como cero. `precio_conocido` dice si el costo es exacto o de resguardo.

Cómo se calcula (precios de la API, por millón de tokens):
    entrada normal        por el precio de entrada
    guardado en la caché  por 1.25 veces la entrada (la primera vez)
    leído de la caché     por 0.10 veces la entrada (las siguientes)
    salida                por el precio de salida
"""

from dataclasses import dataclass

from registro_proveedor.agente.llm.adaptador import Uso

FACTOR_CACHE_ESCRITURA = 1.25
FACTOR_CACHE_LECTURA = 0.10
MODELO_POR_DEFECTO = "claude-haiku-5-5"


@dataclass(frozen=True)
class Precio:
    entrada: float  # USD por millón de tokens de entrada
    salida: float  # USD por millón de tokens de salida


# Precio de cada modelo, por el comienzo de su nombre (así "claude-haiku-5-5-2026…"
# también se reconoce). Para usar otro modelo, agregue aquí su precio oficial.
PRECIOS: dict[str, Precio] = {
    "claude-haiku-5-5": Precio(entrada=0.10, salida=0.50),
}

# Para un modelo que no está en la tabla: un precio alto, para que los topes corten
# antes de tiempo y no después.
PRECIO_DE_RESGUARDO = Precio(entrada=5.00, salida=25.00)


def precio_de(modelo: str) -> Precio:
    for nombre, precio in PRECIOS.items():
        if modelo.startswith(nombre):
            return precio
    return PRECIO_DE_RESGUARDO


def precio_conocido(modelo: str) -> bool:
    return any(modelo.startswith(nombre) for nombre in PRECIOS)


def costo_usd(uso: Uso, modelo: str = MODELO_POR_DEFECTO) -> float:
    """Costo aproximado en dólares, contando la caché. Nunca cero si hubo tokens."""
    precio = precio_de(modelo)
    entrada = (
        uso.entrada
        + uso.cache_escritura * FACTOR_CACHE_ESCRITURA
        + uso.cache_lectura * FACTOR_CACHE_LECTURA
    )
    return (entrada * precio.entrada + uso.salida * precio.salida) / 1_000_000
