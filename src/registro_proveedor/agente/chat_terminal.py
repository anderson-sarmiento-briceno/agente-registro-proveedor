"""Chat con el agente en la terminal, con el modelo REAL (`scripts/chat.py`).

Sirve para probar el agente completo antes de tener la API (Paso 15) y el front
(Paso 16). Después de cada respuesta muestra una tabla con las herramientas que pidió
el modelo, EN ORDEN, con sus argumentos y su resultado. Así se ve exactamente cómo
decidió el modelo.

Confirmaciones (Paso 13): cuando el modelo pide una acción que requiere aprobación,
se muestra como pendiente, con su identificador. La analista la resuelve con:
    /aprobar [id]     /rechazar [id]
o, sin la barra, con la palabra sola: `aprobar`, `rechazar` (o la palabra y el id de
una pendiente). Estos comandos los interpreta ESTE programa, no el modelo: son el
equivalente de los botones Aprobar / Rechazar del front. Si hay una sola pendiente, el
id es opcional. Una frase como "sí, apruébalo" NO es un comando: va al modelo como
mensaje normal y, por eso, cancela las pendientes (RN4). La terminal lo avisa (⊘).

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
# El comando y si aprueba (True) o rechaza (False).
COMANDOS = {"/aprobar": True, "/rechazar": False}
# Las mismas palabras sin la barra: solas, o seguidas del id de una pendiente.
PALABRAS = {"aprobar": True, "rechazar": False}


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
        "Escriba su mensaje, o «salir» para terminar. "
        "Para las acciones pendientes: aprobar o rechazar."
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
        turno = _atender(agente, sesion, mensaje)
        if turno is None:  # un comando mal escrito: ya se explicó, no se llamó al modelo
            escribir(_ayuda_comandos(sesion))
            continue
        escribir(f"\nAgente: {turno.texto}\n")
        escribir(describir_turno(turno))
    escribir(
        f"\nFin de la conversación · {sesion.uso.total} tokens · "
        f"costo aproximado USD {costo_usd(sesion.uso):.4f}"
    )
    return 0


def _atender(agente: Agente, sesion: Sesion, mensaje: str) -> Turno | None:
    """Un mensaje normal va al modelo; `/aprobar` y `/rechazar` resuelven una pendiente.

    Devuelve None si el comando no se puede resolver (por ejemplo, hay dos pendientes y
    no se dijo cuál): en ese caso no se hace nada.
    """
    partes = mensaje.split()
    comando = partes[0].lower()
    if comando in COMANDOS:
        aprobar = COMANDOS[comando]
    elif _es_palabra_de_comando(partes, sesion):
        aprobar = PALABRAS[comando]
    elif comando.startswith("/"):
        return None
    else:
        return agente.responder(sesion, mensaje)
    if len(partes) > 1:
        id_confirmacion = partes[1]
    elif len(sesion.pendientes) == 1:
        id_confirmacion = next(iter(sesion.pendientes))
    else:
        return None
    return agente.resolver(sesion, id_confirmacion, aprobar=aprobar)


def _es_palabra_de_comando(partes: list[str], sesion: Sesion) -> bool:
    """¿Es "aprobar" / "rechazar" sin barra? Solo si está sola, o seguida del id de una pendiente.

    Así "aprobar" funciona como el botón, pero una frase normal que empiece con esa
    palabra ("rechazar la propuesta del cliente…") sigue siendo un mensaje para el modelo.
    """
    if partes[0].lower() not in PALABRAS:
        return False
    return len(partes) == 1 or (len(partes) == 2 and partes[1] in sesion.pendientes)


def _ayuda_comandos(sesion: Sesion) -> str:
    if not sesion.pendientes:
        return "No hay acciones pendientes de aprobación."
    lineas = ["Diga cuál acción resolver: aprobar <id> o rechazar <id>"]
    lineas += [f"  {p.id} · {p.descripcion}" for p in sesion.pendientes.values()]
    return "\n".join(lineas)


def describir_turno(turno: Turno) -> str:
    """La tabla de herramientas que pidió el modelo en el turno, las pendientes y el costo."""
    lineas: list[str] = [
        f"⊘ Se canceló la acción pendiente {p.id} ({p.descripcion}) porque escribió otro "
        "mensaje sin aprobarla. Para aprobar, escriba aprobar o /aprobar."
        for p in turno.canceladas
    ]
    lineas += [
        f"⚠️ El resultado de {a.herramienta} trae texto que parece una instrucción "
        f"({', '.join(a.tipos)}). Se trató como dato del cliente, no como orden."
        for a in turno.alertas
    ]
    if turno.llamadas:
        lineas += [
            "Herramientas que pidió el modelo (en orden):",
            "| # | Herramienta | Argumentos | Resultado |",
            "|---|---|---|---|",
        ]
        lineas += [
            f"| {ll.orden} | {ll.nombre} | {json.dumps(ll.argumentos, ensure_ascii=False)} | "
            f"{ll.simbolo} {ll.resumen} |"
            for ll in turno.llamadas
        ]
    else:
        lineas.append("(El modelo no pidió herramientas en este turno.)")
    if turno.pendientes:
        lineas.append("")
        lineas.append("⏳ Pendientes de su aprobación (escriba aprobar o rechazar):")
        lineas += [f"  {p.id} · {p.descripcion}" for p in turno.pendientes]
    lineas.append(
        f"Fin: {turno.fin} · {turno.consultas} "
        f"{'consulta' if turno.consultas == 1 else 'consultas'} al modelo · "
        f"{turno.uso.total} tokens · USD {costo_usd(turno.uso):.4f}"
    )
    return "\n".join(lineas)
