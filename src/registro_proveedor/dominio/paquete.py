"""Paquete para firma: todo lo que el representante legal necesita, y si está listo o no.

Crea `out/<caso>/paquete/` con:
    - el formulario, generado DE NUEVO desde mapeo.json (nunca va uno viejo);
    - copias de los soportes exigidos que existan (los vencidos también, marcados);
    - checklist.md: listo / no listo, con los motivos y el estado de cada soporte;
    - borrador-correo.md: la respuesta al cliente, SIN datos bancarios (RN2);
    - manifiesto.json: para auditar (HU-7): fechas, versión del maestro, huella de cada
      archivo y el origen de cada campo.

¿Cuándo está "listo_para_firma"?
    Solo si nada lo bloquea. Bloquean:
    - un soporte vencido o ausente (RN3);
    - un campo por confirmar: su celda está vacía en el formulario (D26) y la decisión
      está pendiente en manos de la analista (decisión de Anderson, Paso 8).
    NO bloquea un campo faltante (RN3): no hay nada que decidir; se avisa.

El paquete se arma en una carpeta temporal y, cuando está completo, reemplaza al
anterior de una sola vez. Así nunca queda un paquete a medias ni archivos sobrantes
de una versión anterior.
"""

import hashlib
import shutil
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from registro_proveedor.dominio.casos import CasoLeido
from registro_proveedor.dominio.generadores import generar_formulario
from registro_proveedor.dominio.generadores.comun import verificar_correspondencia
from registro_proveedor.dominio.mapeo import Estado, Mapeo, Metodo, valor_en_maestro
from registro_proveedor.dominio.modelos import (
    NOMBRES_SOPORTE,
    Formato,
    Maestro,
    Solicitud,
    Soporte,
)
from registro_proveedor.dominio.reglas import (
    EstadoSoporte,
    EvaluacionSoporte,
    Reglas,
    evaluar_soportes,
)
from registro_proveedor.dominio.textos import renderizar
from registro_proveedor.observabilidad import RUTAS_SENSIBLES

CARPETA_PAQUETE = "paquete"
ARCHIVO_CHECKLIST = "checklist.md"
ARCHIVO_BORRADOR = "borrador-correo.md"
ARCHIVO_MANIFIESTO = "manifiesto.json"

TEXTO_SOPORTE = {
    EstadoSoporte.PRESENTE: "✅ vigente",
    EstadoSoporte.POR_VENCER: "⚠️ por vencer",
    EstadoSoporte.VENCIDO: "⛔ vencido",
    EstadoSoporte.AUSENTE: "⛔ ausente",
}

# Un valor muy corto ("COP", "7") podría aparecer en cualquier texto por casualidad;
# solo se buscan en el borrador los valores de este largo o más.
LARGO_MINIMO_A_BUSCAR = 4


class ErrorDePaquete(Exception):
    """No se puede armar el paquete; el mensaje dice por qué."""


class _Modelo(BaseModel):
    model_config = ConfigDict(frozen=True)


# ---------- Modelos ----------


class OrigenCampo(_Modelo):
    """De dónde salió cada campo del formulario (sin el valor: ese está en el formulario)."""

    etiqueta: str
    estado: Estado
    ruta: str | None
    metodo: Metodo
    confianza: float
    decision: str | None  # "aceptar" / "dejar_faltante", si la analista decidió
    confirmado_por: str | None
    confirmado_en: datetime | None


class ArchivoDelPaquete(_Modelo):
    """Un archivo del paquete con su huella (SHA-256).

    La huella es como una "firma digital" del contenido: si alguien cambia un solo byte
    del archivo después de armar el paquete, la huella ya no coincide.
    """

    nombre: str
    sha256: str
    bytes: int


class Manifiesto(_Modelo):
    caso: str
    cliente: str
    generado_en: datetime
    fecha_ejecucion: date
    version_maestro: str
    listo_para_firma: bool
    motivos: list[str]
    soportes: list[EvaluacionSoporte]
    campos: list[OrigenCampo]
    archivos: list[ArchivoDelPaquete]


class Paquete(_Modelo):
    """El resultado de armar el paquete (lo que la herramienta resume para el modelo)."""

    carpeta: Path
    listo_para_firma: bool
    motivos: list[str]  # lo que bloquea la firma
    avisos: list[str]  # lo que conviene saber, pero no bloquea
    soportes: list[EvaluacionSoporte]
    archivos: list[str]


# ---------- Armar ----------


def armar_paquete(
    *,
    caso: CasoLeido,
    solicitud: Solicitud,
    mapeo: Mapeo,
    maestro: Maestro,
    indice: list[Soporte],
    carpeta_soportes: Path,
    reglas: Reglas,
    fecha: date,
    generado_en: datetime,
    carpeta_caso: Path,
) -> Paquete:
    """Arma `carpeta_caso/paquete/` y devuelve su resumen.

    Lanza `ErrorDeGeneracion` si el mapeo no corresponde a la plantilla y
    `ErrorDePaquete` si falta un archivo de soporte o el borrador llevaría un dato
    bancario o sensible.
    """
    verificar_correspondencia(mapeo, caso)
    evaluaciones = evaluar_soportes(caso.soportes, indice, fecha, reglas.vigencias)
    motivos, avisos = _motivos_y_avisos(mapeo, evaluaciones)
    listo = not motivos

    destino = carpeta_caso / CARPETA_PAQUETE
    temporal = carpeta_caso / f".{CARPETA_PAQUETE}.tmp"
    shutil.rmtree(temporal, ignore_errors=True)  # restos de un intento anterior fallido
    temporal.mkdir(parents=True)
    try:
        formulario = generar_formulario(mapeo, caso, temporal).ruta.name
        copiados = _copiar_soportes(evaluaciones, carpeta_soportes, temporal)
        borrador = _borrador(caso, solicitud, maestro, indice, evaluaciones, listo)
        _revisar_rn2(borrador, mapeo, maestro, reglas)
        (temporal / ARCHIVO_BORRADOR).write_text(borrador, encoding="utf-8", newline="\n")
        archivos = [formulario, *copiados, ARCHIVO_CHECKLIST, ARCHIVO_BORRADOR]
        checklist = _checklist(caso, mapeo, fecha, evaluaciones, motivos, avisos, listo, archivos)
        (temporal / ARCHIVO_CHECKLIST).write_text(checklist, encoding="utf-8", newline="\n")
        manifiesto = _manifiesto(
            caso, mapeo, fecha, generado_en, evaluaciones, motivos, temporal, archivos
        )
        (temporal / ARCHIVO_MANIFIESTO).write_text(
            manifiesto.model_dump_json(indent=2), encoding="utf-8", newline="\n"
        )
    except BaseException:
        shutil.rmtree(temporal, ignore_errors=True)  # no dejar un paquete a medias
        raise
    # Todo salió bien: el paquete nuevo reemplaza al anterior.
    shutil.rmtree(destino, ignore_errors=True)
    temporal.rename(destino)
    return Paquete(
        carpeta=destino,
        listo_para_firma=listo,
        motivos=motivos,
        avisos=avisos,
        soportes=evaluaciones,
        archivos=[*archivos, ARCHIVO_MANIFIESTO],
    )


def _motivos_y_avisos(
    mapeo: Mapeo, evaluaciones: list[EvaluacionSoporte]
) -> tuple[list[str], list[str]]:
    """Qué bloquea la firma (motivos) y qué solo se avisa."""
    motivos: list[str] = []
    avisos: list[str] = []
    for e in evaluaciones:
        nombre = NOMBRES_SOPORTE[e.tipo]
        if e.bloquea:
            motivos.append(f"soporte {e.estado}: {nombre}, {e.nota}")
        elif e.estado is EstadoSoporte.POR_VENCER:
            avisos.append(f"soporte por vencer: {nombre}, {e.nota}")
    for campo in mapeo.en_estado(Estado.REQUIERE_CONFIRMACION):
        motivos.append(f"campo por confirmar: «{campo.etiqueta}»")
    for campo in mapeo.en_estado(Estado.FALTANTE):
        avisos.append(f"campo faltante en el maestro: «{campo.etiqueta}»")
    return motivos, avisos


def _copiar_soportes(
    evaluaciones: list[EvaluacionSoporte], origen: Path, destino: Path
) -> list[str]:
    """Copia al paquete los soportes que existen (incluidos los vencidos, para renovarlos)."""
    copiados: list[str] = []
    for e in evaluaciones:
        if e.archivo is None:  # ausente: no hay nada que copiar
            continue
        archivo = origen / e.archivo
        if not archivo.is_file():
            raise ErrorDePaquete(
                f"no se encontró el archivo «{e.archivo}» del soporte "
                f"{NOMBRES_SOPORTE[e.tipo]} en el repositorio"
            )
        shutil.copyfile(archivo, destino / e.archivo)  # `datos/` solo se lee
        copiados.append(e.archivo)
    return copiados


# ---------- Borrador del correo y RN2 ----------


def _borrador(
    caso: CasoLeido,
    solicitud: Solicitud,
    maestro: Maestro,
    indice: list[Soporte],
    evaluaciones: list[EvaluacionSoporte],
    listo: bool,
) -> str:
    """El texto del correo de respuesta. Solo recibe lo que necesita: nunca datos bancarios."""
    descripciones = {s.tipo: s.descripcion for s in indice}
    adjuntos = [descripciones[e.tipo] for e in evaluaciones if e.archivo is not None]
    return renderizar(
        f"{ARCHIVO_BORRADOR}.j2",
        para=solicitud.de,
        asunto=solicitud.asunto,
        razon_social=maestro.razon_social,
        portal=caso.formato is Formato.PORTAL,
        adjuntos=adjuntos,
        listo=listo,
    )


def _revisar_rn2(texto: str, mapeo: Mapeo, maestro: Maestro, reglas: Reglas) -> None:
    """RN2, segunda protección: el borrador no puede contener un dato bancario ni sensible.

    La primera protección es que la plantilla no los recibe. Esta revisa el texto ya
    armado, por si alguno llegara por otro lado (por ejemplo, un cliente que escribió
    un número de cuenta en el asunto del correo). Si aparece, el paquete NO se arma.
    El mensaje dice qué dato es, pero no lo muestra.
    """
    contenido = maestro.model_dump(mode="json")
    rutas = [*reglas.datos_bancarios.rutas, *sorted(RUTAS_SENSIBLES)]
    prohibidos = {ruta: valor_en_maestro(contenido, ruta) for ruta in rutas}
    for campo in mapeo.campos:  # también lo que se mapeó (por si viene de otra ruta)
        if campo.ruta in rutas and campo.valor:
            prohibidos.setdefault(campo.ruta, campo.valor)
    # Un valor bancario que TAMBIÉN es un dato público del maestro no es secreto. Por
    # ejemplo, el titular de la cuenta suele ser la razón social, que va en la firma.
    publicos = {
        valor
        for ruta in _rutas_hoja(contenido)
        if ruta not in rutas and (valor := valor_en_maestro(contenido, ruta))
    }
    for ruta, valor in prohibidos.items():
        if valor in publicos:
            continue
        if valor and len(valor) >= LARGO_MINIMO_A_BUSCAR and valor in texto:
            raise ErrorDePaquete(
                f"el borrador del correo contendría un dato bancario o sensible («{ruta}»), "
                "y eso no se permite (RN2). Revise el asunto y el remitente de la solicitud."
            )


def _rutas_hoja(contenido: dict[str, object], prefijo: str = "") -> list[str]:
    """Todas las rutas del maestro que llegan a un valor: "nit", "banco.swift", ...

    Recursiva: si un valor es un grupo (un diccionario), entra en él.
    """
    rutas: list[str] = []
    for clave, valor in contenido.items():
        ruta = f"{prefijo}{clave}"
        if isinstance(valor, dict):
            rutas.extend(_rutas_hoja(valor, f"{ruta}."))
        else:
            rutas.append(ruta)
    return rutas


# ---------- Checklist ----------


def _checklist(
    caso: CasoLeido,
    mapeo: Mapeo,
    fecha: date,
    evaluaciones: list[EvaluacionSoporte],
    motivos: list[str],
    avisos: list[str],
    listo: bool,
    archivos: list[str],
) -> str:
    soportes = [
        {
            "nombre": NOMBRES_SOPORTE[e.tipo],
            "estado": TEXTO_SOPORTE[e.estado],
            "vence": e.vigencia_hasta.isoformat() if e.vigencia_hasta else "—",
            "nota": e.nota,
        }
        for e in evaluaciones
    ]
    return renderizar(
        f"{ARCHIVO_CHECKLIST}.j2",
        cliente=caso.cliente,
        caso=caso.caso,
        fecha=fecha.isoformat(),
        version_maestro=mapeo.version_maestro or "sin versión",
        listo=listo,
        motivos=motivos,
        avisos=avisos,
        soportes=soportes,
        llenos=len(mapeo.en_estado(Estado.LLENO)),
        pendientes=[c.etiqueta for c in mapeo.en_estado(Estado.REQUIERE_CONFIRMACION)],
        faltantes=[c.etiqueta for c in mapeo.en_estado(Estado.FALTANTE)],
        archivos=[*archivos, ARCHIVO_MANIFIESTO],
    )


# ---------- Manifiesto ----------


def _manifiesto(
    caso: CasoLeido,
    mapeo: Mapeo,
    fecha: date,
    generado_en: datetime,
    evaluaciones: list[EvaluacionSoporte],
    motivos: list[str],
    carpeta: Path,
    archivos: list[str],
) -> Manifiesto:
    return Manifiesto(
        caso=caso.caso,
        cliente=caso.cliente,
        generado_en=generado_en,
        fecha_ejecucion=fecha,
        version_maestro=mapeo.version_maestro or "sin versión",
        listo_para_firma=not motivos,
        motivos=motivos,
        soportes=evaluaciones,
        campos=[
            OrigenCampo(
                etiqueta=c.etiqueta,
                estado=c.estado,
                ruta=c.ruta,
                metodo=c.metodo,
                confianza=c.confianza,
                decision=c.confirmacion.decision if c.confirmacion else None,
                confirmado_por=c.confirmacion.por if c.confirmacion else None,
                confirmado_en=c.confirmacion.en if c.confirmacion else None,
            )
            for c in mapeo.campos
        ],
        archivos=[_huella(carpeta / nombre) for nombre in archivos],
    )


def _huella(archivo: Path) -> ArchivoDelPaquete:
    contenido = archivo.read_bytes()
    return ArchivoDelPaquete(
        nombre=archivo.name, sha256=hashlib.sha256(contenido).hexdigest(), bytes=len(contenido)
    )
