"""Envío SIMULADO del paquete para firma (HU-5, Paso 13).

En el MVP "enviar" no manda nada a nadie: escribe `out/<caso>/ENVIO-SIMULADO.md`, que
deja constancia de qué archivos se habrían enviado (con su huella) y quién lo aprobó.

¿Cuándo se niega?
    Enviar un paquete que no corresponde a lo que la analista revisó sería peor que no
    enviar nada. Por eso, antes de escribir, se comprueba que el paquete:
    1. exista (que se haya usado `proveedor_armar_paquete`);
    2. esté LISTO para firma (nada lo bloquea: RN3 y D30);
    3. esté AL DÍA:
       - se armó con la misma fecha de ejecución (si no, las vigencias pudieron cambiar);
       - el mapeo no cambió después (por ejemplo, se confirmó un campo);
       - ningún archivo del paquete cambió ni falta (se comparan las huellas).
    Si algo falla, se lanza `ErrorDeEnvio` con un mensaje que dice qué hacer.

La aprobación de la analista NO se revisa aquí: la exige el doble candado de la capa de
herramientas (Paso 13). Este módulo solo recibe quién aprobó, para anotarlo.

Datos sensibles: el archivo lista nombres, tamaños y huellas, nunca valores.
"""

from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from registro_proveedor.dominio.casos import CasoLeido
from registro_proveedor.dominio.generadores.comun import escribir_atomico
from registro_proveedor.dominio.mapeo import Estado, Mapeo
from registro_proveedor.dominio.paquete import (
    ARCHIVO_MANIFIESTO,
    CARPETA_PAQUETE,
    ArchivoDelPaquete,
    Manifiesto,
    huella_de,
)
from registro_proveedor.dominio.textos import renderizar

ARCHIVO_ENVIO = "ENVIO-SIMULADO.md"
VOLVER_A_ARMAR = "vuelva a usar proveedor_armar_paquete"


class ErrorDeEnvio(Exception):
    """No se puede simular el envío; el mensaje dice por qué y qué hacer."""


class EnvioSimulado(BaseModel):
    model_config = ConfigDict(frozen=True)

    ruta: Path
    archivos: list[ArchivoDelPaquete]  # los del paquete, más el manifiesto


def simular_envio(
    *,
    caso: CasoLeido,
    mapeo: Mapeo,
    carpeta_caso: Path,
    fecha: date,
    aprobacion: str,
    aprobado_por: str,
    aprobado_en: datetime,
) -> EnvioSimulado:
    """Escribe `ENVIO-SIMULADO.md` si el paquete está listo y al día. Lanza `ErrorDeEnvio` si no."""
    paquete = carpeta_caso / CARPETA_PAQUETE
    manifiesto = _leer_manifiesto(paquete, caso.caso)
    _revisar_que_este_listo(manifiesto)
    _revisar_que_este_al_dia(manifiesto, mapeo, fecha, paquete)
    archivos = [*manifiesto.archivos, huella_de(paquete / ARCHIVO_MANIFIESTO)]
    texto = renderizar(
        f"{ARCHIVO_ENVIO.lower()}.j2",
        caso=caso.caso,
        cliente=caso.cliente,
        pais=caso.pais_nombre,
        formato=caso.formato,
        fecha=fecha.isoformat(),
        paquete_generado_en=manifiesto.generado_en.isoformat(),
        aprobacion=aprobacion,
        aprobado_por=aprobado_por,
        aprobado_en=aprobado_en.isoformat(),
        archivos=archivos,
    )
    destino = carpeta_caso / ARCHIVO_ENVIO
    escribir_atomico(destino, lambda ruta: ruta.write_text(texto, encoding="utf-8", newline="\n"))
    return EnvioSimulado(ruta=destino, archivos=archivos)


def _leer_manifiesto(paquete: Path, caso: str) -> Manifiesto:
    ruta = paquete / ARCHIVO_MANIFIESTO
    if not ruta.is_file():
        raise ErrorDeEnvio(
            f"el caso «{caso}» todavía no tiene paquete: primero use proveedor_armar_paquete"
        )
    try:
        return Manifiesto.model_validate_json(ruta.read_text(encoding="utf-8"))
    except ValidationError:
        raise ErrorDeEnvio(f"el manifiesto del paquete está dañado: {VOLVER_A_ARMAR}") from None


def _revisar_que_este_listo(manifiesto: Manifiesto) -> None:
    if not manifiesto.listo_para_firma:
        raise ErrorDeEnvio(
            "el paquete no está listo para firma, así que no se puede enviar. Falta resolver: "
            + "; ".join(manifiesto.motivos)
        )


def _revisar_que_este_al_dia(
    manifiesto: Manifiesto, mapeo: Mapeo, fecha: date, paquete: Path
) -> None:
    if manifiesto.fecha_ejecucion != fecha:
        raise ErrorDeEnvio(
            f"el paquete se armó con la fecha {manifiesto.fecha_ejecucion} y la fecha de "
            f"ejecución ahora es {fecha}: {VOLVER_A_ARMAR} para revisar las vigencias"
        )
    if _estado_de_campos(manifiesto) != _estado_de_campos_del_mapeo(mapeo):
        raise ErrorDeEnvio(
            "el mapeo cambió después de armar el paquete (por ejemplo, se confirmó un "
            f"campo): {VOLVER_A_ARMAR}"
        )
    for esperado in manifiesto.archivos:
        archivo = paquete / esperado.nombre
        if not archivo.is_file() or huella_de(archivo).sha256 != esperado.sha256:
            raise ErrorDeEnvio(
                f"el archivo «{esperado.nombre}» del paquete cambió o falta desde que se "
                f"armó: {VOLVER_A_ARMAR}"
            )


# Lo que identifica el estado de un campo: su etiqueta, su estado y la decisión de la
# analista, si la hubo. Si algo de esto cambió, el formulario del paquete ya no es el
# que corresponde al mapeo.
_EstadoCampo = tuple[str, Estado, str | None]


def _estado_de_campos(manifiesto: Manifiesto) -> list[_EstadoCampo]:
    return [(c.etiqueta, c.estado, c.decision) for c in manifiesto.campos]


def _estado_de_campos_del_mapeo(mapeo: Mapeo) -> list[_EstadoCampo]:
    return [
        (c.etiqueta, c.estado, c.confirmacion.decision if c.confirmacion else None)
        for c in mapeo.campos
    ]
