"""Chat con el agente en la terminal, con el modelo REAL (`scripts/chat.py`).

Sirve para probar el agente completo antes de tener la API (Paso 15) y el front
(Paso 16). Después de cada respuesta muestra una tabla con las herramientas que pidió
el modelo, EN ORDEN, con sus argumentos y su resultado. Así se ve exactamente cómo
decidió el modelo.

Gasta dinero de verdad (poco: un caso completo son unas 6 consultas a
claude-haiku-5-5, del orden de un centavo de dólar) y necesita la clave en `.env`.
Lo que genera queda en `out/`, igual que con la demo.

`leer` y `escribir` se reciben como parámetros (en vez de usar `input` y `print`
directamente) para que las pruebas puedan simular a la persona que escribe.
"""

import json
from collections.abc import Callable

from registro_proveedor.agente.ciclo import Agente, Sesion, Turno
from registro_proveedor.agente.instrucciones import cargar_instrucciones
from registro_proveedor.agente.llm.adaptador import AdaptadorLLM, ErrorDelModelo
from registro_proveedor.agente.llm.proveedor_anthropic import AdaptadorAnthropic
from registro_proveedor.agente.llm.prueba_real import costo_usd
from registro_proveedor.config import Configuracion
from registro_proveedor.dominio.lectura import ErrorDeDatos
from registro_proveedor.herramientas.proveedor import registro

PALABRAS_PARA_SALIR = {"salir", "exit", "quit"}


def conversar(
    config: Configuracion,
    *,
    leer: Callable[[str], str] = input,
    escribir: Callable[[str], None] = print,
    adaptador: AdaptadorLLM | None = None,
    sesion: Sesion | None = None,
) -> int:
    """Conversa hasta que la persona escriba «salir». Devuelve el código de salida.

    `adaptador` y `sesion` solo los usan las pruebas (modelo falso y `out/` temporal).
    """
    try:
        instrucciones = cargar_instrucciones()
        modelo = adaptador or AdaptadorAnthropic.desde_configuracion(config)
    except (ErrorDeDatos, ErrorDelModelo) as e:
        escribir(f"ERROR: {e.mensaje if isinstance(e, ErrorDelModelo) else e}")
        return 1
    agente = Agente.desde_configuracion(
        config, adaptador=modelo, registro=registro, instrucciones=instrucciones
    )
    sesion = sesion or Sesion.nueva(config)
    escribir(
        f"Agente de registro como proveedor · modelo {modelo.modelo} · "
        f"instrucciones v{instrucciones.version} · sesión {sesion.id}\n"
        "Escriba su mensaje, o «salir» para terminar."
    )
    while True:
        try:
            mensaje = leer("\nUsted: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if mensaje.lower() in PALABRAS_PARA_SALIR:
            break
        if not mensaje:
            continue
        turno = agente.responder(sesion, mensaje)
        escribir(f"\nAgente: {turno.texto}\n")
        escribir(describir_turno(turno))
    escribir(
        f"\nFin de la conversación · {sesion.uso.total} tokens · "
        f"costo aproximado USD {costo_usd(sesion.uso):.4f}"
    )
    return 0


def describir_turno(turno: Turno) -> str:
    """La tabla de herramientas que pidió el modelo en el turno, y lo que costó."""
    if turno.llamadas:
        lineas = [
            "Herramientas que pidió el modelo (en orden):",
            "| # | Herramienta | Argumentos | Resultado |",
            "|---|---|---|---|",
        ]
        lineas += [
            f"| {ll.orden} | {ll.nombre} | {json.dumps(ll.argumentos, ensure_ascii=False)} | "
            f"{'✓' if ll.ok else '✗'} {ll.resumen} |"
            for ll in turno.llamadas
        ]
    else:
        lineas = ["(El modelo no pidió herramientas en este turno.)"]
    lineas.append(
        f"Fin: {turno.fin} · {turno.consultas} consultas al modelo · "
        f"{turno.uso.total} tokens · USD {costo_usd(turno.uso):.4f}"
    )
    return "\n".join(lineas)
