"""Las métricas del piloto (Paso 21): los objetivos O1 a O5 del plan, caso por caso.

De dónde sale cada dato (nada se anota a mano, salvo la planilla):
    - `out/<caso>/mapeo.json`: cómo quedó cada campo (lleno, faltante, por confirmar) y
      lo que decidió la analista. Si un caso se trabajó varias veces, vale el más reciente.
    - `out/<caso>/paquete/manifiesto.json`: si quedó listo y el estado de los soportes.
    - `out/<caso>/log.jsonl`: cada herramienta, con su hora, si salió bien y su aprobación.
    - `out/costos.jsonl` y `out/retroalimentacion.jsonl`: el costo y los 👍 / 👎.
    - `piloto/esperado/<caso>.json`: la "respuesta correcta" de los casos nuevos (qué dato
      del maestro corresponde a cada etiqueta). Con ella se miden aciertos y errores.
    - `piloto/planilla.md`: lo que el sistema no puede medir (el tiempo a mano, O4).

Los objetivos (sección 3 del plan):
    O1 · % de los campos que EXISTEN en el maestro que se llenaron solos (meta 100 %).
    O2 · 0 valores inventados: cada valor coincide con su fuente en el maestro.
    O3 · 0 acciones sin aprobación: cada confirmación y cada envío tienen la suya.
    O4 · menos de 15 minutos de trabajo por solicitud (de la planilla).
    O5 · 100 % de los soportes vencidos o por vencer señalados.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from registro_proveedor.dominio.lectura import cargar_maestro
from registro_proveedor.dominio.mapeo import (
    ARCHIVO_MAPEO,
    Decision,
    Estado,
    Mapeo,
    cargar_mapeo,
    valor_en_maestro,
)
from registro_proveedor.dominio.modelos import NOMBRES_SOPORTE
from registro_proveedor.dominio.paquete import ARCHIVO_MANIFIESTO, CARPETA_PAQUETE, Manifiesto
from registro_proveedor.dominio.reglas import EstadoSoporte
from registro_proveedor.observabilidad import ARCHIVO_AUDITORIA, RegistroLlamada, costo_por_caso
from registro_proveedor.piloto.retroalimentacion import Opinion, leer_opiniones

CON_APROBACION = frozenset({"proveedor_confirmar_campo", "proveedor_registrar_envio"})
META_MINUTOS = 15


@dataclass
class Exactitud:
    """Comparación con la respuesta correcta (`piloto/esperado/`), campo por campo."""

    aciertos: int = 0  # lleno con el dato correcto
    por_confirmar_correctos: int = 0  # propuso el dato correcto, pero pidió confirmar
    no_reconocidos: list[str] = field(default_factory=list)  # existía y quedó faltante
    # GRAVE: se llenó SOLO con un dato del maestro, pero de OTRO campo (o uno que no existe).
    errores: list[str] = field(default_factory=list)
    # Menos grave: propuso un dato equivocado, pero quedó por confirmar (la analista lo ve).
    propuestas_erroneas: list[str] = field(default_factory=list)
    faltantes_reales: int = 0  # no existe en el maestro y quedó faltante: bien
    sugerencias: dict[str, str] = field(default_factory=dict)  # etiqueta → ruta, para el glosario


@dataclass
class MetricasDeCaso:
    caso: str
    cliente: str
    total: int
    llenos: int
    faltantes: int
    por_confirmar: int
    aceptados: int  # decisiones de la analista
    dejados_vacios: int
    existen_en_maestro: int | None  # con respuesta correcta: cuántos campos SÍ existen
    llenos_correctos: int | None
    exactitud: Exactitud | None
    inventados: list[str]  # O2: valores que no coinciden con el maestro
    listo: bool | None
    soportes_alerta: int  # vencidos o por vencer
    soportes_senalados: int
    acciones: int  # confirmaciones y envíos ejecutados
    acciones_sin_aprobacion: int
    errores_herramientas: int
    minutos_con_agente: float | None
    usd: float

    @property
    def o1(self) -> float | None:
        if not self.existen_en_maestro or self.llenos_correctos is None:
            return None
        return self.llenos_correctos / self.existen_en_maestro


@dataclass(frozen=True)
class FilaPlanilla:
    caso: str
    minutos_a_mano: float | None
    minutos_con_agente: float | None
    errores: str
    comentarios: str


@dataclass
class Piloto:
    casos: list[MetricasDeCaso]
    opiniones: list[Opinion]
    planilla: list[FilaPlanilla]


# ---------- Leer ----------


def medir(salida: Path, datos: Path, esperado: Path, planilla: Path) -> Piloto:
    """Las métricas de todos los casos trabajados en `salida`."""
    contenido = cargar_maestro(datos).model_dump(mode="json")
    costos = {c.caso: c.usd for c in costo_por_caso(salida)}
    casos = [
        _medir_caso(carpeta, contenido, _esperado(esperado, carpeta.name), costos)
        for carpeta in _carpetas_de_casos(salida)
    ]
    return Piloto(casos=casos, opiniones=leer_opiniones(salida), planilla=leer_planilla(planilla))


def _carpetas_de_casos(salida: Path) -> list[Path]:
    """La carpeta más reciente de cada caso que tenga mapeo (en out/ o en out/sesiones/…)."""
    recientes: dict[str, Path] = {}
    for mapeo in salida.rglob(ARCHIVO_MAPEO):
        carpeta = mapeo.parent
        anterior = recientes.get(carpeta.name)
        if anterior is None or mapeo.stat().st_mtime > (anterior / ARCHIVO_MAPEO).stat().st_mtime:
            recientes[carpeta.name] = carpeta
    return [recientes[c] for c in sorted(recientes)]


def _esperado(carpeta: Path, caso: str) -> dict[str, str | None] | None:
    ruta = carpeta / f"{caso}.json"
    if not ruta.exists():
        return None
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    return {str(k): (str(v) if v is not None else None) for k, v in contenido.items()}


def _medir_caso(
    carpeta: Path,
    contenido: dict[str, object],
    esperado: dict[str, str | None] | None,
    costos: dict[str, float],
) -> MetricasDeCaso:
    mapeo = cargar_mapeo(carpeta)
    assert mapeo is not None  # la carpeta se eligió porque tiene mapeo.json
    manifiesto = _manifiesto(carpeta)
    llamadas = _llamadas(carpeta)
    campos = mapeo.campos
    decisiones = [c.confirmacion.decision for c in campos if c.confirmacion is not None]
    exactitud = _exactitud(mapeo, esperado) if esperado is not None else None
    alerta = [
        s
        for s in (manifiesto.soportes if manifiesto else [])
        if s.estado in (EstadoSoporte.VENCIDO, EstadoSoporte.POR_VENCER)
    ]
    checklist = _checklist(carpeta)
    acciones = [ll for ll in llamadas if ll.herramienta in CON_APROBACION and ll.ok]
    return MetricasDeCaso(
        caso=mapeo.caso,
        cliente=manifiesto.cliente if manifiesto else mapeo.caso,
        total=len(campos),
        llenos=sum(c.estado is Estado.LLENO for c in campos),
        faltantes=sum(c.estado is Estado.FALTANTE for c in campos),
        por_confirmar=sum(c.estado is Estado.REQUIERE_CONFIRMACION for c in campos),
        aceptados=decisiones.count(Decision.ACEPTAR),
        dejados_vacios=decisiones.count(Decision.DEJAR_FALTANTE),
        existen_en_maestro=(
            sum(1 for r in esperado.values() if r is not None) if esperado is not None else None
        ),
        llenos_correctos=exactitud.aciertos if exactitud is not None else None,
        exactitud=exactitud,
        inventados=_inventados(mapeo, contenido),
        listo=manifiesto.listo_para_firma if manifiesto else None,
        soportes_alerta=len(alerta),
        soportes_senalados=sum(NOMBRES_SOPORTE[s.tipo] in checklist for s in alerta),
        acciones=len(acciones),
        acciones_sin_aprobacion=sum(ll.aprobacion is None for ll in acciones),
        errores_herramientas=sum(
            not ll.ok and ll.herramienta not in CON_APROBACION for ll in llamadas
        ),
        minutos_con_agente=_minutos(llamadas),
        usd=costos.get(mapeo.caso, 0.0),
    )


def _manifiesto(carpeta: Path) -> Manifiesto | None:
    ruta = carpeta / CARPETA_PAQUETE / ARCHIVO_MANIFIESTO
    try:
        return Manifiesto.model_validate_json(ruta.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        return None


def _checklist(carpeta: Path) -> str:
    ruta = carpeta / CARPETA_PAQUETE / "checklist.md"
    return ruta.read_text(encoding="utf-8") if ruta.exists() else ""


def _llamadas(carpeta: Path) -> list[RegistroLlamada]:
    ruta = carpeta / ARCHIVO_AUDITORIA
    if not ruta.exists():
        return []
    llamadas: list[RegistroLlamada] = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        try:
            llamadas.append(RegistroLlamada.model_validate_json(linea))
        except ValidationError:
            continue
    return llamadas


def _minutos(llamadas: list[RegistroLlamada]) -> float | None:
    """De la primera a la última herramienta del caso: el tiempo de punta a punta."""
    momentos: list[datetime] = [ll.ts for ll in llamadas]
    if len(momentos) < 2:
        return None
    return (max(momentos) - min(momentos)).total_seconds() / 60


def _exactitud(mapeo: Mapeo, esperado: dict[str, str | None]) -> Exactitud:
    resultado = Exactitud()
    for campo in mapeo.campos:
        correcta = esperado.get(campo.etiqueta)
        # Si la analista ya decidió, cuenta su decisión: lo que quedó en el formulario.
        destino = (
            resultado.errores if campo.estado is Estado.LLENO else resultado.propuestas_erroneas
        )
        if correcta is None:
            if campo.estado is Estado.FALTANTE:
                resultado.faltantes_reales += 1
            else:
                destino.append(f"{campo.etiqueta} (no existe en el maestro)")
        elif campo.estado is Estado.FALTANTE:
            resultado.no_reconocidos.append(campo.etiqueta)
            resultado.sugerencias[campo.etiqueta] = correcta
        elif campo.ruta != correcta:
            destino.append(f"{campo.etiqueta} (usó {campo.ruta}, era {correcta})")
        elif campo.estado is Estado.LLENO:
            resultado.aciertos += 1
        else:
            resultado.por_confirmar_correctos += 1
    return resultado


def _inventados(mapeo: Mapeo, contenido: dict[str, object]) -> list[str]:
    """O2: los campos con un valor que NO es el de su fuente en el maestro."""
    return [
        c.etiqueta
        for c in mapeo.campos
        if c.valor is not None
        and (c.ruta is None or valor_en_maestro(contenido, c.ruta) != c.valor)
    ]


def leer_planilla(ruta: Path) -> list[FilaPlanilla]:
    """Las filas de la tabla de `piloto/planilla.md` que tengan algo anotado."""
    if not ruta.exists():
        return []
    filas: list[FilaPlanilla] = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        if len(celdas) != 5 or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", celdas[0]):
            continue
        a_mano, con_agente = _numero(celdas[1]), _numero(celdas[2])
        if a_mano is None and con_agente is None and not celdas[3] and not celdas[4]:
            continue
        filas.append(FilaPlanilla(celdas[0], a_mano, con_agente, celdas[3], celdas[4]))
    return filas


def _numero(texto: str) -> float | None:
    try:
        return float(texto.replace(",", "."))
    except ValueError:
        return None


# ---------- El reporte ----------


def reporte(piloto: Piloto, cuando: datetime) -> str:
    casos = piloto.casos
    lineas = [
        "# Reporte del piloto · Registro como Proveedor",
        "",
        f"Generado el {cuando:%Y-%m-%d %H:%M} con `scripts/metricas_piloto.py`. "
        f"Casos trabajados: **{len(casos)}**.",
        "",
        "## Objetivos del plan",
        "",
        "| Objetivo | Meta | Resultado | |",
        "|---|---|---|---|",
        *_filas_de_objetivos(piloto),
        "",
        "## Caso por caso",
        "",
        "| Caso | Campos | Llenos | Faltantes | Por confirmar | Decisiones | O1 | Listo | "
        "Errores de herramientas | Minutos | USD |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in casos:
        lineas.append(
            f"| {c.caso} | {c.total} | {c.llenos} | {c.faltantes} | {c.por_confirmar} | "
            f"{c.aceptados} aceptados · {c.dejados_vacios} vacíos | {_porcentaje(c.o1)} | "
            f"{_si_no(c.listo)} | {c.errores_herramientas} | {_minutos_texto(c.minutos_con_agente)}"
            f" | {c.usd:.4f} |"
        )
    lineas += _detalle_de_exactitud(casos)
    lineas += _seccion_opiniones(piloto.opiniones)
    lineas += _seccion_planilla(piloto.planilla)
    return "\n".join(lineas) + "\n"


def _filas_de_objetivos(piloto: Piloto) -> list[str]:
    casos = piloto.casos
    con_esperado = [c for c in casos if c.o1 is not None]
    existen = sum(c.existen_en_maestro or 0 for c in con_esperado)
    correctos = sum(c.llenos_correctos or 0 for c in con_esperado)
    o1 = correctos / existen if existen else None
    inventados = sum(len(c.inventados) for c in casos)
    equivocados = sum(len(c.exactitud.errores) for c in con_esperado if c.exactitud)
    acciones = sum(c.acciones for c in casos)
    sin_aprobacion = sum(c.acciones_sin_aprobacion for c in casos)
    alerta = sum(c.soportes_alerta for c in casos)
    senalados = sum(c.soportes_senalados for c in casos)
    con_tiempo = [f for f in piloto.planilla if f.minutos_con_agente is not None]
    promedio = (
        sum(f.minutos_con_agente or 0 for f in con_tiempo) / len(con_tiempo) if con_tiempo else None
    )
    return [
        f"| O1 · Llenar sin transcribir (casos nuevos) | 100 % | {_porcentaje(o1)} "
        f"({correctos} de {existen} campos que existen en el maestro) | {_marca(o1 == 1.0)} |",
        f"| O2 · Ningún valor inventado | 0 | {inventados} | {_marca(inventados == 0)} |",
        f"| O2 · Ningún valor en el campo equivocado (casos nuevos) | 0 | {equivocados} | "
        f"{_marca(equivocados == 0)} |",
        f"| O3 · Ninguna acción sin aprobación | 0 | {sin_aprobacion} de {acciones} acciones | "
        f"{_marca(sin_aprobacion == 0)} |",
        f"| O4 · Minutos de trabajo por solicitud (planilla) | < {META_MINUTOS} | "
        f"{_minutos_texto(promedio)} en promedio ({len(con_tiempo)} casos anotados) | "
        f"{_marca(promedio < META_MINUTOS) if promedio is not None else 'falta anotar'} |",
        f"| O5 · Soportes vencidos o por vencer señalados | 100 % | {senalados} de {alerta} | "
        f"{_marca(senalados == alerta)} |",
    ]


def _detalle_de_exactitud(casos: list[MetricasDeCaso]) -> list[str]:
    con = [c for c in casos if c.exactitud is not None]
    if not con:
        return []
    lineas = [
        "",
        "## Exactitud del mapeo (casos nuevos, contra la respuesta correcta)",
        "",
        "| Caso | Aciertos | Por confirmar (dato correcto) | No reconocidos | "
        "Llenados en el campo equivocado | Propuestas equivocadas | Faltantes reales |",
        "|---|---|---|---|---|---|---|",
    ]
    sugerencias: dict[str, str] = {}
    detalle: list[str] = []
    for c in con:
        e = c.exactitud
        assert e is not None
        lineas.append(
            f"| {c.caso} | {e.aciertos} | {e.por_confirmar_correctos} | "
            f"{len(e.no_reconocidos)} | {len(e.errores)} | {len(e.propuestas_erroneas)} | "
            f"{e.faltantes_reales} |"
        )
        sugerencias.update(e.sugerencias)
        detalle += [f"- ⛔ **{c.caso}** · llenado en el campo equivocado: {x}" for x in e.errores]
        detalle += [
            f"- ⚠️ **{c.caso}** · propuesta equivocada (por confirmar): {x}"
            for x in e.propuestas_erroneas
        ]
    if detalle:
        lineas += ["", *detalle]
    if sugerencias:
        lineas += [
            "",
            "**Etiquetas que existían en el maestro y no se reconocieron** (candidatas al "
            "glosario, con la aprobación del dueño del dato):",
            "",
            "| Etiqueta del cliente | Dato del maestro |",
            "|---|---|",
            *(f"| {e} | `{r}` |" for e, r in sorted(sugerencias.items())),
        ]
    return lineas


def _seccion_opiniones(opiniones: list[Opinion]) -> list[str]:
    lineas = ["", "## Opiniones en el chat (👍 / 👎)", ""]
    if not opiniones:
        return [*lineas, "Todavía no hay opiniones registradas."]
    utiles = sum(o.util for o in opiniones)
    lineas.append(f"**{utiles} 👍 · {len(opiniones) - utiles} 👎** de {len(opiniones)}.")
    comentarios = [o for o in opiniones if o.comentario]
    if comentarios:
        lineas += ["", "| | Casos | Comentario |", "|---|---|---|"]
        lineas += [
            f"| {'👍' if o.util else '👎'} | {', '.join(o.casos) or '—'} | "
            f"{(o.comentario or '').replace('|', '/')} |"
            for o in comentarios
        ]
    return lineas


def _seccion_planilla(planilla: list[FilaPlanilla]) -> list[str]:
    lineas = ["", "## Planilla (lo que anotó quien hizo el piloto)", ""]
    if not planilla:
        return [*lineas, "La planilla `piloto/planilla.md` todavía está vacía."]
    lineas += [
        "| Caso | Minutos a mano | Minutos con el agente | Errores encontrados | Comentarios |",
        "|---|---|---|---|---|",
    ]
    lineas += [
        f"| {f.caso} | {_minutos_texto(f.minutos_a_mano)} | {_minutos_texto(f.minutos_con_agente)}"
        f" | {f.errores} | {f.comentarios} |"
        for f in planilla
    ]
    return lineas


def _porcentaje(valor: float | None) -> str:
    return f"{valor:.0%}" if valor is not None else "—"


def _minutos_texto(valor: float | None) -> str:
    return f"{valor:.1f}" if valor is not None else "—"


def _si_no(valor: bool | None) -> str:
    return "—" if valor is None else ("Sí" if valor else "No")


def _marca(cumple: bool) -> str:
    return "✅" if cumple else "⚠️"
