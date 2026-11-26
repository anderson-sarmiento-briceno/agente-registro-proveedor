"""Corre los escenarios con el agente y escribe el reporte de evaluación (Paso 17).

Cómo se corre un escenario:
    1. Se copia `datos/` a una carpeta temporal (y, si el escenario lo pide, se le mete
       el texto malicioso a la COPIA). `out/` también es temporal: la evaluación no
       toca ni los datos reales ni el `out/` de la demo.
    2. Se crea una sesión nueva con la fecha fija de la evaluación (2026-09-20, la misma
       de la demo del front: Colombia y Panamá pueden llegar a "listo").
    3. Se hace cada acción del guion: un mensaje (`Agente.responder`) o un clic en
       Aprobar (`Agente.resolver`), exactamente como lo hacen la API y la terminal.
    4. Se revisan los criterios y se borra la carpeta temporal.

Presupuesto:
    Con el modelo real, cada escenario cuesta dinero. Antes de empezar cada uno se
    revisa lo gastado: si ya llegó al tope (`tope_usd`), los que faltan se marcan como
    "no se corrió" en vez de gastar más.

El reporte (Markdown):
    Un archivo por corrida en `evals/reportes/`, con la fecha, la versión del prompt,
    el modelo y el esfuerzo en el nombre. Así se comparan versiones en git. Trae:
        - el resumen escenario por escenario (✓ / ✗ y costo);
        - la matriz de herramientas que pidió el modelo, en orden, por cada turno;
        - el detalle de cada criterio que falló.
    No incluye las respuestas completas del modelo: basta con lo que se verificó.
"""

import argparse
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from registro_proveedor.agente.ciclo import Agente, Sesion
from registro_proveedor.agente.instrucciones import InstruccionesSistema, cargar_instrucciones
from registro_proveedor.agente.llm.adaptador import AdaptadorLLM, ErrorDelModelo, Uso
from registro_proveedor.agente.llm.proveedor_anthropic import AdaptadorAnthropic
from registro_proveedor.agente.llm.prueba_real import costo_usd
from registro_proveedor.config import RAIZ_PROYECTO, Configuracion
from registro_proveedor.dominio.lectura import ErrorDeDatos
from registro_proveedor.evaluacion.escenarios import (
    COMUNES,
    Criterio,
    Ejecucion,
    Escenario,
    Escribe,
    TurnoEvaluado,
    escenarios,
)
from registro_proveedor.herramientas.base import Contexto, reloj_para
from registro_proveedor.herramientas.proveedor import registro

# Fecha fija de las evaluaciones (RN7): el resultado no depende del día en que se corren.
FECHA_EVALUACION = date(2026, 9, 20)
CARPETA_REPORTES = RAIZ_PROYECTO / "evals" / "reportes"
TOPE_USD_POR_DEFECTO = 0.25


@dataclass(frozen=True)
class ResultadoCriterio:
    nombre: str
    falla: str | None  # None = se cumplió

    @property
    def ok(self) -> bool:
        return self.falla is None


@dataclass(frozen=True)
class ResultadoEscenario:
    escenario: Escenario
    turnos: tuple[TurnoEvaluado, ...]
    criterios: tuple[ResultadoCriterio, ...]
    uso: Uso
    corrido: bool = True  # False = no se corrió porque se llegó al tope de dinero

    @property
    def ok(self) -> bool:
        return self.corrido and all(c.ok for c in self.criterios)

    @property
    def costo(self) -> float:
        return costo_usd(self.uso)


@dataclass(frozen=True)
class Evaluacion:
    """El resultado de una corrida completa."""

    modelo: str
    esfuerzo: str
    instrucciones: InstruccionesSistema
    fecha_datos: date
    resultados: tuple[ResultadoEscenario, ...]
    tope_usd: float

    @property
    def costo(self) -> float:
        return sum(r.costo for r in self.resultados)


# ---------- Correr ----------


def correr_escenario(
    escenario: Escenario,
    *,
    adaptador: AdaptadorLLM,
    instrucciones: InstruccionesSistema,
    config: Configuracion,
    datos: Path,
    fecha: date = FECHA_EVALUACION,
) -> ResultadoEscenario:
    """Corre UN escenario en una carpeta temporal y revisa sus criterios."""
    with tempfile.TemporaryDirectory(prefix=f"eval-{escenario.id}-") as temporal:
        carpeta = Path(temporal)
        copia = carpeta / "datos"
        shutil.copytree(datos, copia)
        if escenario.preparar is not None:
            escenario.preparar(copia)
        contexto = Contexto(
            datos=copia,
            salida=carpeta / "out",
            fecha_ejecucion=fecha,
            sesion_id=f"eval-{escenario.id.lower()}",
            reloj=reloj_para(fecha),
        )
        sesion = Sesion(contexto)
        agente = Agente.desde_configuracion(
            config, adaptador=adaptador, registro=registro, instrucciones=instrucciones
        )
        ejecucion = _conversar(agente, sesion, escenario)
        criterios = tuple(_revisar(c, ejecucion) for c in (*escenario.criterios, *COMUNES))
    return ResultadoEscenario(
        escenario=escenario,
        turnos=tuple(ejecucion.turnos),
        criterios=criterios,
        uso=sesion.uso,
    )


def _conversar(agente: Agente, sesion: Sesion, escenario: Escenario) -> Ejecucion:
    """Hace las acciones del guion, una por una, y guarda cada turno."""
    ejecucion = Ejecucion()
    for accion in escenario.acciones:
        if isinstance(accion, Escribe):
            turno = agente.responder(sesion, accion.texto)
        else:
            pendiente = next(
                (p for p in sesion.pendientes.values() if p.herramienta == accion.herramienta),
                None,
            )
            if pendiente is None:
                # El modelo no dejó pendiente lo que la analista iba a aprobar: el resto
                # del guion ya no tiene sentido. Los criterios lo marcarán.
                ejecucion.problema = (
                    f"paso {len(ejecucion.turnos) + 1}: no había nada pendiente de "
                    f"{accion.herramienta} para aprobar"
                )
                break
            turno = agente.resolver(sesion, pendiente.id, aprobar=True)
        ejecucion.turnos.append(TurnoEvaluado(accion, turno, _archivos(sesion.contexto.salida)))
    return ejecucion


def _archivos(salida: Path) -> frozenset[str]:
    if not salida.is_dir():
        return frozenset()
    return frozenset(p.relative_to(salida).as_posix() for p in salida.rglob("*") if p.is_file())


def _revisar(criterio: Criterio, ejecucion: Ejecucion) -> ResultadoCriterio:
    return ResultadoCriterio(criterio.nombre, criterio.revisar(ejecucion))


def evaluar(
    lista: list[Escenario],
    *,
    crear_adaptador: Callable[[Escenario], AdaptadorLLM],
    instrucciones: InstruccionesSistema,
    config: Configuracion,
    datos: Path,
    tope_usd: float = TOPE_USD_POR_DEFECTO,
    avisar: Callable[[str], None] = lambda _: None,
) -> Evaluacion:
    """Corre todos los escenarios, sin pasarse del tope de dinero.

    `crear_adaptador` da el modelo para cada escenario: con el real es siempre el mismo;
    en las pruebas, un modelo falso con el guion de ese escenario.
    `avisar` muestra el avance en la terminal ("E3 ✓ · USD 0.0061").
    """
    resultados: list[ResultadoEscenario] = []
    modelo = ""
    for escenario in lista:
        gastado = sum(r.costo for r in resultados)
        if gastado >= tope_usd:
            resultados.append(_no_corrido(escenario))
            avisar(f"{escenario.id} — no se corrió: ya se gastó el tope de USD {tope_usd:.2f}")
            continue
        adaptador = crear_adaptador(escenario)
        modelo = adaptador.modelo
        resultado = correr_escenario(
            escenario,
            adaptador=adaptador,
            instrucciones=instrucciones,
            config=config,
            datos=datos,
        )
        resultados.append(resultado)
        avisar(
            f"{escenario.id} {'✓' if resultado.ok else '✗'} {escenario.titulo} · "
            f"USD {resultado.costo:.4f}"
        )
    return Evaluacion(
        modelo=modelo or config.llm_modelo,
        esfuerzo=config.llm_esfuerzo,
        instrucciones=instrucciones,
        fecha_datos=FECHA_EVALUACION,
        resultados=tuple(resultados),
        tope_usd=tope_usd,
    )


def _no_corrido(escenario: Escenario) -> ResultadoEscenario:
    return ResultadoEscenario(
        escenario=escenario, turnos=(), criterios=(), uso=Uso(), corrido=False
    )


# ---------- El reporte ----------


def nombre_reporte(evaluacion: Evaluacion, cuando: datetime) -> str:
    """ "2026-11-26_1530_prompt-v6_claude-haiku-5-5_medium.md"."""
    return (
        f"{cuando:%Y-%m-%d_%H%M}_prompt-v{evaluacion.instrucciones.version}_"
        f"{evaluacion.modelo}_{evaluacion.esfuerzo}.md"
    )


def escribir_reporte(evaluacion: Evaluacion, carpeta: Path, cuando: datetime) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / nombre_reporte(evaluacion, cuando)
    ruta.write_text(reporte(evaluacion, cuando), encoding="utf-8", newline="\n")
    return ruta


def reporte(evaluacion: Evaluacion, cuando: datetime) -> str:
    """El reporte en Markdown."""
    corridos = [r for r in evaluacion.resultados if r.corrido]
    aprobados = sum(r.ok for r in corridos)
    total_criterios = sum(len(r.criterios) for r in corridos)
    criterios_ok = sum(c.ok for r in corridos for c in r.criterios)
    ins = evaluacion.instrucciones
    lineas = [
        f"# Evaluación del agente · prompt v{ins.version} · {evaluacion.modelo} · "
        f"esfuerzo {evaluacion.esfuerzo}",
        "",
        "| Dato | Valor |",
        "|---|---|",
        f"| Corrida | {cuando:%Y-%m-%d %H:%M} |",
        f"| Prompt | versión {ins.version} · huella `{ins.huella}` |",
        f"| Modelo | {evaluacion.modelo} · esfuerzo {evaluacion.esfuerzo} |",
        f"| Fecha de los datos | {evaluacion.fecha_datos.isoformat()} |",
        f"| Escenarios | {aprobados} de {len(evaluacion.resultados)} aprobados"
        + (
            f" ({len(evaluacion.resultados) - len(corridos)} sin correr por el tope)"
            if len(corridos) < len(evaluacion.resultados)
            else ""
        )
        + " |",
        f"| Criterios | {criterios_ok} de {total_criterios} cumplidos |",
        f"| Costo aproximado | USD {evaluacion.costo:.4f} (tope USD {evaluacion.tope_usd:.2f}) |",
        "",
        "## Resumen",
        "",
        "| # | Escenario | Resultado | Criterios | Tokens | USD |",
        "|---|---|---|---|---|---|",
    ]
    for r in evaluacion.resultados:
        if not r.corrido:
            lineas.append(f"| {r.escenario.id} | {r.escenario.titulo} | — sin correr | — | — | — |")
            continue
        cumplidos = sum(c.ok for c in r.criterios)
        lineas.append(
            f"| {r.escenario.id} | {r.escenario.titulo} | {'✓' if r.ok else '✗'} | "
            f"{cumplidos}/{len(r.criterios)} | {r.uso.total} | {r.costo:.4f} |"
        )
    lineas += [
        "",
        "## Herramientas que pidió el modelo, en orden",
        "",
        "✓ ejecutada · ✗ falló · ⏳ quedó pendiente de aprobación · ✓ aprobada · ⊘ rechazada",
    ]
    for r in corridos:
        lineas += ["", f"### {r.escenario.id} · {r.escenario.titulo}", ""]
        lineas += _matriz(r)
        lineas += ["", "| Criterio | Resultado |", "|---|---|"]
        lineas += [
            f"| {c.nombre} | {'✓' if c.ok else '✗ ' + _celda(c.falla or '')} |" for c in r.criterios
        ]
    return "\n".join(lineas) + "\n"


def _matriz(resultado: ResultadoEscenario) -> list[str]:
    """Una fila por turno: qué hizo la analista y qué herramientas pidió el modelo."""
    filas = ["| Turno | La analista | Herramientas (en orden) | Fin |", "|---|---|---|---|"]
    for i, t in enumerate(resultado.turnos, start=1):
        herramientas = " → ".join(
            f"{ll.simbolo} {ll.nombre.removeprefix('proveedor_')}" for ll in t.turno.llamadas
        )
        filas.append(
            f"| {i} | {_celda(t.accion.describir())} | {herramientas or '(ninguna)'} | "
            f"{t.turno.fin} |"
        )
    return filas


def _celda(texto: str) -> str:
    """Un texto dentro de una celda de tabla Markdown: sin "|" ni saltos de línea."""
    return texto.replace("|", "\\|").replace("\n", " ")


# ---------- Desde la terminal (scripts/evaluar.py) ----------


def principal(
    argv: list[str] | None = None,
    *,
    config: Configuracion,
    escribir: Callable[[str], None] = print,
    crear_adaptador: Callable[[Escenario], AdaptadorLLM] | None = None,
    carpeta: Path = CARPETA_REPORTES,
    datos: Path = RAIZ_PROYECTO / "datos",
) -> int:
    """Lee las opciones, corre la evaluación y escribe el reporte. Devuelve el código de salida.

    0 = todos los escenarios corridos pasaron · 1 = alguno falló o no se corrió ·
    2 = no se pudo empezar (sin clave, escenario inexistente…).
    `crear_adaptador` solo lo pasan las pruebas (modelo falso): sin él, se usa el real.
    """
    opciones = _leer_opciones(argv)
    if opciones.esfuerzo:
        config = config.model_copy(update={"llm_esfuerzo": opciones.esfuerzo})
    lista = escenarios(datos)
    if opciones.escenario:
        pedidos = {e.upper() for e in opciones.escenario}
        desconocidos = pedidos - {e.id for e in lista}
        if desconocidos:
            escribir(f"ERROR: no existe el escenario {', '.join(sorted(desconocidos))}")
            return 2
        lista = [e for e in lista if e.id in pedidos]
    try:
        instrucciones = cargar_instrucciones()
        if crear_adaptador is None:
            real = AdaptadorAnthropic.desde_configuracion(config)
            crear_adaptador = lambda _escenario: real  # noqa: E731 (el mismo para todos)
    except (ErrorDeDatos, ErrorDelModelo) as e:
        escribir(f"ERROR: {e.mensaje if isinstance(e, ErrorDelModelo) else e}")
        return 2
    escribir(
        f"Evaluando {len(lista)} escenarios · prompt v{instrucciones.version} · "
        f"{config.llm_modelo} · esfuerzo {config.llm_esfuerzo} · tope USD {opciones.tope_usd:.2f}"
    )
    evaluacion = evaluar(
        lista,
        crear_adaptador=crear_adaptador,
        instrucciones=instrucciones,
        config=config,
        datos=datos,
        tope_usd=opciones.tope_usd,
        avisar=escribir,
    )
    ruta = escribir_reporte(evaluacion, carpeta, datetime.now())
    aprobados = sum(r.ok for r in evaluacion.resultados)
    escribir(
        f"\n{aprobados} de {len(evaluacion.resultados)} escenarios aprobados · "
        f"costo aproximado USD {evaluacion.costo:.4f}\nReporte: {ruta}"
    )
    return 0 if aprobados == len(evaluacion.resultados) else 1


@dataclass(frozen=True)
class _Opciones:
    esfuerzo: str | None
    escenario: list[str]
    tope_usd: float


def _leer_opciones(argv: list[str] | None) -> _Opciones:
    lector = argparse.ArgumentParser(
        description="Evalúa el agente con el modelo REAL (gasta dinero, poco)."
    )
    lector.add_argument(
        "--esfuerzo",
        choices=["low", "medium", "high"],
        help="Cambia LLM_ESFUERZO solo para esta corrida (para comparar, CA6).",
    )
    lector.add_argument(
        "--escenario",
        action="append",
        default=[],
        help="Corre solo ese escenario (E1…E7). Se puede repetir.",
    )
    lector.add_argument(
        "--tope-usd",
        type=float,
        default=TOPE_USD_POR_DEFECTO,
        help=f"No empieza otro escenario si ya se gastó esto (por defecto {TOPE_USD_POR_DEFECTO}).",
    )
    ns = lector.parse_args(argv)
    return _Opciones(esfuerzo=ns.esfuerzo, escenario=list(ns.escenario), tope_usd=ns.tope_usd)
