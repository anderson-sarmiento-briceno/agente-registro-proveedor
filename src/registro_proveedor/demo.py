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

# Fecha fija de la demo (RN7): con ella el resultado es siempre el mismo. La Cámara de
# Comercio vence el 2026-09-30, así que con la fecha de hoy estaría vencida.
FECHA_DEMO = date(2026, 9, 1)
NOMBRE_SALIDA = "out"


class ErrorDeDemo(Exception):
    """Un problema al preparar la demo (por ejemplo, una carpeta de salida peligrosa)."""


@dataclass(frozen=True)
class ResultadoDemo:
    codigo: int  # 0 = todas las herramientas respondieron bien; 1 = alguna falló
    texto: str  # el resumen para mostrar en la terminal


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
    """La fecha de la demo: la del argumento; si no hay, la de `.env`; si no, la fecha fija.

    `--fecha hoy` usa la fecha real de hoy.
    """
    if argumento == "hoy":
        return date.today()
    if argumento is not None:
        return date.fromisoformat(argumento)
    return config.fecha_ejecucion or FECHA_DEMO


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
    for caso in pedidos:
        if caso not in disponibles:
            lineas += [f"{caso}", f"  ERROR: no existe el caso «{caso}»", ""]
            con_error += 1
            continue
        ok, listo, bloque = _procesar_caso(caso, ctx)
        lineas += [*bloque, ""]
        con_error += 0 if ok else 1
        listos += 1 if listo else 0

    procesados = len(pedidos) - con_error
    lineas.append(
        f"Resultado: {_cantidad(procesados, 'caso procesado', 'casos procesados')} · "
        f"{_cantidad(listos, 'listo', 'listos')} para firma · "
        f"{_cantidad(procesados - listos, 'no listo', 'no listos')} · {con_error} con error"
    )
    return ResultadoDemo(1 if con_error else 0, "\n".join(lineas))


def _procesar_caso(caso: str, ctx: Contexto) -> tuple[bool, bool, list[str]]:
    """Un caso de punta a punta. Devuelve (todo salió bien, listo para firma, líneas)."""
    argumentos = {"caso": caso}
    leido = _llamar("proveedor_leer_solicitud", argumentos, ctx)
    if not leido.ok:
        return False, False, [caso, f"  ERROR al leer: {leido.error}"]
    s = _datos(leido)
    lineas = [f"{caso} · {s.cliente} · {s.pais_nombre} · {s.formato}"]

    for nombre, accion in (
        ("proveedor_mapear_campos", "mapear"),
        ("proveedor_generar_formulario", "generar el formulario"),
        ("proveedor_armar_paquete", "armar el paquete"),
    ):
        r = _llamar(nombre, argumentos, ctx)
        if not r.ok:
            return False, False, [*lineas, f"  ERROR al {accion}: {r.error}"]
        lineas += _describir(nombre, _datos(r))
        if nombre == "proveedor_armar_paquete":
            return True, bool(_datos(r).listo_para_firma), lineas
    raise AssertionError("no se llega aquí")  # el ciclo siempre termina en el paquete


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


# ---------- Terminal ----------


def main(argumentos: list[str], config: Configuracion | None = None) -> ResultadoDemo:
    """Lee los argumentos de la terminal y ejecuta la demo."""
    parser = argparse.ArgumentParser(
        prog="demo.py", description="Procesa los casos de ejemplo sin modelo de lenguaje."
    )
    parser.add_argument(
        "--fecha", help=f"AAAA-MM-DD u «hoy». Por defecto, {FECHA_DEMO.isoformat()}."
    )
    parser.add_argument(
        "--caso", action="append", help="Procesa solo este caso (se puede repetir)."
    )
    parser.add_argument(
        "--salida", type=Path, default=RAIZ_PROYECTO / NOMBRE_SALIDA, help="Carpeta «out»."
    )
    args = parser.parse_args(argumentos)
    try:
        fecha = elegir_fecha(args.fecha, config or Configuracion())
    except ValueError:
        parser.error(f"fecha no válida: «{args.fecha}» (use AAAA-MM-DD u «hoy»)")
    try:
        return ejecutar_demo(RAIZ_PROYECTO / "datos", args.salida, fecha, args.caso)
    except ErrorDeDemo as e:
        return ResultadoDemo(1, f"ERROR: {e}")
