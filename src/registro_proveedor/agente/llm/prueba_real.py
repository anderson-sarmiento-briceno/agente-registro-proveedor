"""Prueba REAL del adaptador: una sola pregunta al modelo, para ver qué herramienta pide.

Le manda al modelo una pregunta de la analista junto con las instrucciones reales del
agente (`agente/prompt.md` + `knowledge/`, Paso 11) y las herramientas del registro,
y muestra lo que el modelo respondió: qué herramienta PIDIÓ y con qué argumentos. NO la
ejecuta (eso lo hará el ciclo del Paso 12). Así se comprueba, antes de construir el
agente, que el modelo entiende las herramientas y elige bien.

Gasta dinero de verdad (muy poco: una llamada a claude-haiku-5-5 cuesta una fracción de
centavo) y necesita la clave en `.env`. Por eso no se ejecuta en las pruebas automáticas:
la corre una persona con `scripts/probar_modelo.py`.
"""

import json

from anthropic import DefaultHttpxClient

from registro_proveedor.agente.instrucciones import InstruccionesSistema, cargar_instrucciones
from registro_proveedor.agente.llm.adaptador import (
    DefinicionHerramienta,
    ErrorDelModelo,
    Mensaje,
    MotivoFin,
    RespuestaModelo,
    Uso,
    definiciones_desde_registro,
)
from registro_proveedor.agente.llm.proveedor_anthropic import AdaptadorAnthropic
from registro_proveedor.config import Configuracion
from registro_proveedor.dominio.lectura import ErrorDeDatos
from registro_proveedor.herramientas.proveedor import registro

PREGUNTA_POR_DEFECTO = "¿Qué solicitudes de registro hay? Busca la del cliente de Ecuador."

# Precio de claude-haiku-5-5 (dólares por millón de tokens, prompts de hasta 100K tokens).
PRECIO_ENTRADA_USD = 0.10
PRECIO_SALIDA_USD = 0.50
# Guardar algo en la caché cuesta un poco MÁS que la entrada normal (la primera vez);
# leerlo de la caché, mucho MENOS (las veces siguientes).
FACTOR_CACHE_ESCRITURA = 1.25
FACTOR_CACHE_LECTURA = 0.10

EXPLICACION_MOTIVO = {
    MotivoFin.PIDE_HERRAMIENTA: "pide herramientas (el ciclo del Paso 12 las ejecutaría)",
    MotivoFin.TERMINO: "respondió con texto, sin pedir herramientas",
    MotivoFin.LIMITE_TOKENS: "se quedó sin espacio (suba LLM_MAX_TOKENS)",
    MotivoFin.PAUSA: "el proveedor pausó el turno",
    MotivoFin.RECHAZO: "el proveedor se negó a responder",
}


def probar(
    config: Configuracion,
    pregunta: str = PREGUNTA_POR_DEFECTO,
    http_client: DefaultHttpxClient | None = None,
) -> tuple[int, str]:
    """Hace la llamada real y devuelve (código de salida, texto para mostrar).

    `http_client` solo lo usan las pruebas, para simular la red.
    """
    herramientas = definiciones_desde_registro(registro)
    try:
        # El sistema real del agente (Paso 11): prompt + conocimiento.
        instrucciones = cargar_instrucciones()
    except ErrorDeDatos as e:
        return 1, f"ERROR (instrucciones): {e}"
    try:
        adaptador = AdaptadorAnthropic.desde_configuracion(config, http_client=http_client)
        respuesta = adaptador.enviar(
            instrucciones.texto, [Mensaje.del_usuario(pregunta)], herramientas
        )
    except ErrorDelModelo as e:
        return 1, f"ERROR ({e.codigo}): {e.mensaje}"
    return 0, describir(config, instrucciones, pregunta, herramientas, respuesta)


def describir(
    config: Configuracion,
    instrucciones: InstruccionesSistema,
    pregunta: str,
    herramientas: list[DefinicionHerramienta],
    respuesta: RespuestaModelo,
) -> str:
    """El resultado de la prueba, para la terminal."""
    lineas = [
        f"Modelo: {respuesta.modelo} · esfuerzo: {config.llm_esfuerzo}",
        f"Instrucciones: versión {instrucciones.version} · huella {instrucciones.huella}",
        f"Herramientas ofrecidas ({len(herramientas)}): "
        + ", ".join(h.nombre for h in herramientas),
        f"Pregunta: {pregunta}",
        "",
        f"Resultado: {EXPLICACION_MOTIVO[respuesta.motivo]}",
    ]
    if respuesta.llamadas:
        lineas += ["", "| # | Herramienta que pidió el modelo | Argumentos |", "|---|---|---|"]
        lineas += [
            f"| {i} | {ll.nombre} | {json.dumps(ll.argumentos, ensure_ascii=False)} |"
            for i, ll in enumerate(respuesta.llamadas, start=1)
        ]
    if respuesta.texto:
        lineas += ["", f"Texto del modelo: {respuesta.texto}"]
    uso = respuesta.uso
    lineas += [
        "",
        f"Tokens: {uso.entrada} de entrada · {uso.salida} de salida · "
        f"{uso.cache_lectura} leídos de la caché · {uso.cache_escritura} guardados en la caché",
        f"Costo aproximado: USD {costo_usd(uso):.5f} (incluye la caché)",
    ]
    return "\n".join(lineas)


def costo_usd(uso: Uso) -> float:
    """Costo aproximado de una llamada en dólares, contando la caché.

    Cada tipo de token tiene su precio: la entrada normal, la salida, lo que se guarda
    en la caché (1.25 veces la entrada) y lo que se lee de ella (0.1 veces la entrada).
    """
    entrada = (
        uso.entrada
        + uso.cache_escritura * FACTOR_CACHE_ESCRITURA
        + uso.cache_lectura * FACTOR_CACHE_LECTURA
    )
    return (entrada * PRECIO_ENTRADA_USD + uso.salida * PRECIO_SALIDA_USD) / 1_000_000
