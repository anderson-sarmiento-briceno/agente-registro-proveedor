"""Envío del paquete para firma, en modo piloto (HU-5, Paso 13).

En el MVP "enviar" no manda nada a nadie: escribe `out/<caso>/constancia-envio.md`, una
constancia formal con el destinatario y el asunto (los del correo del cliente), los
archivos del paquete con su huella y quién aprobó el envío. La entrega al cliente se
hace fuera del sistema; la constancia lo dice una vez, en su última línea.

¿Por qué no se llama "ENVIO-SIMULADO.md"? (decisión de Anderson, opción A)
    La constancia debe verse como un documento de trabajo profesional, sin repetir
    "simulado" por todas partes, pero SIN fingir que se envió algo: la última línea dice
    que es modo piloto. La herramienta (`proveedor_registrar_envio`) y el prompt le dicen
    al modelo que no se envía nada al cliente, para que nunca diga que el paquete ya
    llegó; pero le piden decirlo UNA vez, sin repetir "simulación" en cada respuesta.
    Para un envío real (correo o portal), ver el Paso 19.

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

Datos sensibles: el archivo lista nombres, tamaños y huellas, nunca valores del
formulario. El destinatario es el correo del cliente, que ya venía en su solicitud.
"""

from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from registro_proveedor.dominio.casos import CasoLeido
from registro_proveedor.dominio.generadores.comun import escribir_atomico
from registro_proveedor.dominio.mapeo import Estado, Mapeo
from registro_proveedor.dominio.modelos import Solicitud
from registro_proveedor.dominio.paquete import (
    ARCHIVO_MANIFIESTO,
    CARPETA_PAQUETE,
    ArchivoDelPaquete,
    Manifiesto,
    huella_de,
)
from registro_proveedor.dominio.textos import renderizar

ARCHIVO_ENVIO = "constancia-envio.md"
VOLVER_A_ARMAR = "vuelva a usar proveedor_armar_paquete"


class ErrorDeEnvio(Exception):
    """No se puede registrar el envío; el mensaje dice por qué y qué hacer."""


class EnvioRegistrado(BaseModel):
    model_config = ConfigDict(frozen=True)

    ruta: Path
    archivos: list[ArchivoDelPaquete]  # los del paquete, más el manifiesto


def registrar_envio(
    *,
    caso: CasoLeido,
    solicitud: Solicitud,
    mapeo: Mapeo,
    carpeta_caso: Path,
    fecha: date,
    aprobacion: str,
    aprobado_por: str,
    aprobado_en: datetime,
) -> EnvioRegistrado:
    """Escribe la constancia si el paquete está listo y al día. Lanza `ErrorDeEnvio` si no."""
    paquete = carpeta_caso / CARPETA_PAQUETE
    manifiesto = _leer_manifiesto(paquete, caso.caso)
    _revisar_que_este_listo(manifiesto)
    _revisar_que_este_al_dia(manifiesto, mapeo, fecha, paquete)
    archivos = [*manifiesto.archivos, huella_de(paquete / ARCHIVO_MANIFIESTO)]
    texto = renderizar(
        f"{ARCHIVO_ENVIO}.j2",
        caso=caso.caso,
        cliente=caso.cliente,
        pais=caso.pais_nombre,
        formato=caso.formato_nombre,
        destinatario=solicitud.de,  # quien escribió el correo es a quien se le responde
        asunto=f"Re: {solicitud.asunto}",
        fecha=fecha.isoformat(),
        paquete_generado_en=_legible(manifiesto.generado_en),
        aprobacion=aprobacion,
        aprobado_por=aprobado_por,
        aprobado_en=_legible(aprobado_en),
        archivos=archivos,
    )
    destino = carpeta_caso / ARCHIVO_ENVIO
    escribir_atomico(destino, lambda ruta: ruta.write_text(texto, encoding="utf-8", newline="\n"))
    return EnvioRegistrado(ruta=destino, archivos=archivos)


def _legible(momento: datetime) -> str:
    """2026-11-26T18:26:09.371599+00:00 → "2026-11-26 18:26 UTC" (para personas)."""
    return momento.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


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
