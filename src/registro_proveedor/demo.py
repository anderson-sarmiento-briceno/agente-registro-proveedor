"""Demostración sin modelo de lenguaje: procesa los casos de punta a punta con las herramientas.

¿Para qué?
    Comprobar que el núcleo funciona SOLO, sin clave de Anthropic (principio 7). Si la
    demo no funciona, el agente tampoco funcionará (sugerencia S2). Además, su salida es
    siempre la misma con la misma fecha, y las pruebas "golden" la comparan.

¿Qué hace?
    1. Limpia la carpeta de salida (`out/`).
    2. Para cada caso, llama a las herramientas por el MISMO camino que usará el agente
       (`registro.ejecutar`): leer → mapear → generar el formulario → armar el paquete.
    3. Devuelve un resumen en texto y un código: 0 si todas las herramientas respondieron
       bien, 1 si alguna falló. Un paquete "no listo" NO es un error: es un resultado.

No confirma ningún campo: eso le toca a una persona (principio 3). Por eso los casos con
un identificador extranjero quedan "no listos".

La puerta de entrada desde la terminal es `scripts/demo.py`.
"""

import argparse
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from registro_proveedor.config import RAIZ_PROYECTO, Configuracion
from registro_proveedor.herramientas.base import Contexto, Resultado
from registro_proveedor.herramientas.proveedor import registro

# Desde la revisión de Anderson (2026-11-26) la demo usa la fecha REAL de hoy: no se
# inventan fechas de ejecución. Las pruebas sí pasan una fecha fija (RN7), para que su
# resultado no dependa del día en que se corren.
NOMBRE_SALIDA = "out"


class ErrorDeDemo(Exception):
    """Un problema al preparar la demo (por ejemplo, una carpeta de salida peligrosa)."""


@dataclass(frozen=True)
class ResultadoDemo:
    codigo: int  # 0 = todas las herramientas respondieron bien; 1 = alguna falló
    texto: str  # el resumen para mostrar en la terminal
    matriz: str = ""  # casos por herramientas (se muestra con --llamadas)


# Las herramientas que se llaman para cada caso, en orden: nombre, para qué (en los
# mensajes de error) y título de su columna en la matriz.
PASOS = (
    ("proveedor_leer_solicitud", "leer", "1. Leer solicitud"),
    ("proveedor_mapear_campos", "mapear", "2. Mapear campos"),
    ("proveedor_generar_formulario", "generar el formulario", "3. Generar formulario"),
    ("proveedor_armar_paquete", "armar el paquete", "4. Armar paquete"),
)
# ✓ y ✗ (y no ✅ ⛔) porque ocupan una sola columna en la terminal y no descuadran la tabla.
BIEN, MAL = "✓", "✗"


# ---------- Preparación ----------


def preparar_salida(salida: Path) -> None:
    """Borra y vuelve a crear la carpeta de salida (el plan pide limpiar `out/` al iniciar).

    Por seguridad, solo borra una carpeta que se llame `out`. Si alguien escribe
    `--salida C:\\` o `--salida datos` por error, se niega en vez de borrar algo valioso.
    """
    if salida.resolve().name != NOMBRE_SALIDA:
        raise ErrorDeDemo(
            f"por seguridad, la carpeta de salida debe llamarse «{NOMBRE_SALIDA}» "
            f"(se recibió «{salida}»)"
        )
    shutil.rmtree(salida, ignore_errors=True)
    salida.mkdir(parents=True)


def contexto_demo(datos: Path, salida: Path, fecha: date) -> Contexto:
    """El contexto de la demo: fecha y hora fijas, para que el resultado sea reproducible."""
    hora = datetime.combine(fecha, time(12, 0), tzinfo=UTC)
    return Contexto(
        datos=datos,
        salida=salida,
        fecha_ejecucion=fecha,
        sesion_id="demo",
        usuario="demo",
        reloj=lambda: hora,
    )


def elegir_fecha(argumento: str | None, config: Configuracion) -> date:
    """La fecha de la demo: la del argumento; si no hay, la de `.env`; si no, la de hoy.

    `--fecha hoy` también usa la fecha real de hoy.
    """
    if argumento == "hoy":
        return date.today()
    if argumento is not None:
        return date.fromisoformat(argumento)
    return config.fecha_ejecucion or date.today()


# ---------- Ejecución ----------


def ejecutar_demo(
    datos: Path, salida: Path, fecha: date, casos: list[str] | None = None
) -> ResultadoDemo:
    """Procesa los casos (todos, o solo los pedidos) y devuelve el resumen."""
    preparar_salida(salida)
    ctx = contexto_demo(datos, salida, fecha)
    lineas = [
        f"Demostración sin modelo de lenguaje · fecha de ejecución {fecha.isoformat()}",
        "",
    ]
    listado = _llamar("proveedor_listar_casos", {}, ctx)
    if not listado.ok:
        return ResultadoDemo(1, "\n".join([*lineas, f"ERROR al listar los casos: {listado.error}"]))
    disponibles = [c.caso for c in _datos(listado).casos]
    pedidos = casos or disponibles

    con_error = listos = 0
    filas: list[tuple[str, dict[str, str]]] = []  # para la matriz: caso → celda por herramienta
    for caso in pedidos:
        if caso not in disponibles:
            lineas += [f"{caso}", f"  ERROR: no existe el caso «{caso}»", ""]
            filas.append((caso, {PASOS[0][0]: f"{MAL} no existe el caso"}))
            con_error += 1
            continue
        ok, listo, bloque, celdas = _procesar_caso(caso, ctx)
        lineas += [*bloque, ""]
        filas.append((caso, celdas))
        con_error += 0 if ok else 1
        listos += 1 if listo else 0

    procesados = len(pedidos) - con_error
    lineas.append(
        f"Resultado: {_cantidad(procesados, 'caso procesado', 'casos procesados')} · "
        f"{_cantidad(listos, 'listo', 'listos')} para firma · "
        f"{_cantidad(procesados - listos, 'no listo', 'no listos')} · {con_error} con error"
    )
    listado_texto = f"{BIEN} {_cantidad(len(disponibles), 'caso', 'casos')}"
    return ResultadoDemo(1 if con_error else 0, "\n".join(lineas), _matriz(listado_texto, filas))


def _procesar_caso(caso: str, ctx: Contexto) -> tuple[bool, bool, list[str], dict[str, str]]:
    """Un caso de punta a punta: llama a las 4 herramientas de `PASOS`, en orden.

    Devuelve (todo salió bien, listo para firma, líneas del resumen, celdas de la matriz).
    Si una herramienta falla, se detiene ahí: las siguientes dependen de ella.
    """
    lineas = [caso]
    celdas: dict[str, str] = {}
    listo = False
    for nombre, accion, _ in PASOS:
        r = _llamar(nombre, {"caso": caso}, ctx)
        if not r.ok:
            celdas[nombre] = f"{MAL} error"
            return False, False, [*lineas, f"  ERROR al {accion}: {r.error}"], celdas
        datos = _datos(r)
        celdas[nombre] = f"{BIEN} {_celda(nombre, datos)}"
        if nombre == "proveedor_leer_solicitud":
            lineas = [f"{caso} · {datos.cliente} · {datos.pais_nombre} · {datos.formato}"]
        else:
            lineas += _describir(nombre, datos)
        if nombre == "proveedor_armar_paquete":
            listo = bool(datos.listo_para_firma)
    return True, listo, lineas, celdas


# `Any`: `registro.ejecutar` devuelve un Resultado de cualquier herramienta (ver base.py).
# Aquí se sabe cuál se llamó, así que se leen sus atributos directamente.
def _llamar(nombre: str, argumentos: Mapping[str, object], ctx: Contexto) -> Resultado[Any]:
    return registro.ejecutar(nombre, argumentos, ctx)


def _datos(resultado: Resultado[Any]) -> Any:
    """Los datos de un resultado exitoso. Las herramientas de la demo siempre devuelven datos."""
    assert resultado.ok and resultado.data is not None
    return resultado.data


def _describir(herramienta: str, datos: Any) -> list[str]:
    """Las líneas del resumen para el resultado de una herramienta."""
    if herramienta == "proveedor_mapear_campos":
        return [
            f"  campos: {_cantidad(len(datos.llenos), 'lleno', 'llenos')} · "
            f"{_cantidad(len(datos.faltantes), 'faltante', 'faltantes')} · "
            f"{len(datos.requiere_confirmacion)} por confirmar"
        ]
    if herramienta == "proveedor_generar_formulario":
        return [f"  formulario: {datos.archivo}"]
    estado = "✅ listo para firma" if datos.listo_para_firma else "⛔ NO listo para firma"
    lineas = [f"  paquete: {estado} ({datos.carpeta})"]
    lineas += [f"    - {m}" for m in datos.motivos]
    if datos.avisos:
        lineas.append("  avisos (no bloquean):")
        lineas += [f"    - {a}" for a in datos.avisos]
    return lineas


def _cantidad(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


# ---------- Matriz de llamadas (opción --llamadas) ----------

ARCHIVO_LLAMADAS = "llamadas.md"


def _celda(herramienta: str, datos: Any) -> str:
    """Lo que dice la celda de una herramienta en la matriz: corto, lo esencial."""
    if herramienta == "proveedor_leer_solicitud":
        return f"{datos.formato} · {len(datos.campos)} campos · {len(datos.soportes)} soportes"
    if herramienta == "proveedor_mapear_campos":
        return (
            f"{_cantidad(len(datos.llenos), 'lleno', 'llenos')} · "
            f"{_cantidad(len(datos.faltantes), 'faltante', 'faltantes')} · "
            f"{len(datos.requiere_confirmacion)} por confirmar"
        )
    if herramienta == "proveedor_generar_formulario":
        return str(datos.archivo).rsplit("/", 1)[-1]  # solo el nombre del archivo
    if datos.listo_para_firma:
        return "listo para firma"
    return f"NO listo ({_cantidad(len(datos.motivos), 'motivo', 'motivos')})"


def _matriz(listado: str, filas: list[tuple[str, dict[str, str]]]) -> str:
    """Una fila por caso y una columna por herramienta, en el orden en que se llaman.

    Es la secuencia que hará el agente con el modelo de lenguaje. Sirve para comprobar el
    núcleo ANTES de conectar el modelo. La tabla es Markdown válido y además se lee bien
    en la terminal, porque las columnas se rellenan con espacios. No lleva tiempos, así
    que con la misma fecha sale siempre igual (y se compara en las pruebas golden).
    """
    encabezado = ("Caso", *(titulo for _, _, titulo in PASOS))
    renglones = [
        (caso, *(celdas.get(nombre, "—") for nombre, _, _ in PASOS)) for caso, celdas in filas
    ]
    return (
        f"Antes de los casos: proveedor_listar_casos → {listado}\n\n"
        f"{_tabla([encabezado, *renglones])}\n\n"
        f"{BIEN} = la herramienta respondió bien · {MAL} = falló · — = no se llegó a llamar"
    )


def _tabla(filas: list[tuple[str, ...]]) -> str:
    """Tabla Markdown con las columnas alineadas (la primera fila es el encabezado)."""
    anchos = [max(len(fila[c]) for fila in filas) for c in range(len(filas[0]))]

    def linea(celdas: tuple[str, ...]) -> str:
        return "| " + " | ".join(t.ljust(a) for t, a in zip(celdas, anchos, strict=True)) + " |"

    separador = "|" + "|".join("-" * (a + 2) for a in anchos) + "|"
    return "\n".join([linea(filas[0]), separador, *(linea(f) for f in filas[1:])])


# ---------- Terminal ----------


def main(argumentos: list[str], config: Configuracion | None = None) -> ResultadoDemo:
    """Lee los argumentos de la terminal y ejecuta la demo."""
    parser = argparse.ArgumentParser(
        prog="demo.py", description="Procesa los casos de ejemplo sin modelo de lenguaje."
    )
    parser.add_argument("--fecha", help="AAAA-MM-DD u «hoy». Por defecto, la fecha de hoy.")
    parser.add_argument(
        "--caso", action="append", help="Procesa solo este caso (se puede repetir)."
    )
    parser.add_argument(
        "--salida", type=Path, default=RAIZ_PROYECTO / NOMBRE_SALIDA, help="Carpeta «out»."
    )
    parser.add_argument(
        "--llamadas",
        action="store_true",
        help=f"Muestra al final la tabla de llamadas a herramientas (y la guarda en "
        f"out/{ARCHIVO_LLAMADAS}).",
    )
    args = parser.parse_args(argumentos)
    config = config or Configuracion()
    try:
        fecha = elegir_fecha(args.fecha, config)
    except ValueError:
        parser.error(f"fecha no válida: «{args.fecha}» (use AAAA-MM-DD u «hoy»)")
    try:
        # Paso 21: `datos/`, o la carpeta del piloto si CARPETA_DATOS la indica.
        resultado = ejecutar_demo(config.datos_efectivos(), args.salida, fecha, args.caso)
    except ErrorDeDemo as e:
        return ResultadoDemo(1, f"ERROR: {e}")
    if not args.llamadas:
        return resultado
    (args.salida / ARCHIVO_LLAMADAS).write_text(
        f"# Llamadas a herramientas · demo del {fecha.isoformat()}\n\n{resultado.matriz}\n",
        encoding="utf-8",
        newline="\n",
    )
    texto = f"{resultado.texto}\n\nLlamadas a herramientas por caso:\n\n{resultado.matriz}"
    return ResultadoDemo(resultado.codigo, texto, resultado.matriz)
