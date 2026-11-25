"""Listado y lectura de los casos de `datos/casos/` (la lógica de las herramientas del Paso 4).

Aquí no hay nada de herramientas ni de agente: solo funciones del dominio que reciben
la carpeta de datos y devuelven modelos. Las herramientas (`herramientas/proveedor.py`)
son envolturas delgadas sobre estas funciones.

- `listar_casos`: qué casos hay, con un filtro opcional ("Ecuador", "andina").
- `leer_caso`: qué pide un caso (país, formato, campos y soportes), con la misma forma
  para los tres formatos (Excel, PDF y portal).
"""

from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from registro_proveedor.dominio.lectura import (
    ARCHIVO_PLANTILLA_CAMPOS,
    ARCHIVO_SOLICITUD,
    CARPETA_CASOS,
    ErrorDeDatos,
    cargar_plantilla_campos,
    cargar_plantilla_celdas,
    cargar_solicitud,
    cargar_soportes_exigidos,
    carpeta_de_caso,
)
from registro_proveedor.dominio.modelos import (
    NOMBRES_PAIS,
    Formato,
    Pais,
    Solicitud,
    TipoSoporte,
)
from registro_proveedor.dominio.texto import palabras

# Una palabra del filtro de 4 letras o más puede coincidir con el COMIENZO de una
# palabra ("indus" encuentra "industrias"). Las más cortas deben coincidir completas:
# si no, "co" (Colombia) encontraría también "corp" (el caso de Ecuador).
LARGO_MINIMO_PARA_PREFIJO = 4

AVISO_PORTAL = (
    "el cliente usa un portal web: no se genera un formulario; "
    "se prepararán los valores listos para copiar (valores-portal.md)"
)
AVISO_PORTAL_SIN_CAMPOS = (
    "el caso de portal no tiene plantilla-campos.json: no se sabe qué campos pide el portal"
)


class _Modelo(BaseModel):
    model_config = ConfigDict(frozen=True)


# ---------- Listado ----------


class ResumenCaso(_Modelo):
    """Un caso en el listado: lo justo para reconocerlo."""

    caso: str
    cliente: str
    pais: Pais
    pais_nombre: str
    formato: Formato
    fecha: date


class CasoConError(_Modelo):
    """Un caso que no se pudo leer. Se lista aparte para no ocultarlo."""

    caso: str
    error: str


class ListadoCasos(_Modelo):
    filtro: str | None
    casos: list[ResumenCaso]
    casos_con_error: list[CasoConError]


def listar_casos(datos: Path, filtro: str | None = None) -> ListadoCasos:
    """Lista los casos de `datos/casos/`, opcionalmente filtrados por cliente o país.

    Un caso roto no detiene el listado (HU-6): va a `casos_con_error` y los demás se
    listan igual. Si el filtro coincide con varios casos se devuelven todos, para que
    el agente pregunte cuál es (HU-1).
    """
    carpeta_casos = datos / CARPETA_CASOS
    if not carpeta_casos.is_dir():
        raise ErrorDeDatos(carpeta_casos, ["no existe la carpeta de casos"])
    casos: list[ResumenCaso] = []
    con_error: list[CasoConError] = []
    # `sorted`: siempre el mismo orden (alfabético), para que el resultado sea predecible.
    for carpeta in sorted(p for p in carpeta_casos.iterdir() if p.is_dir()):
        try:
            resumen = _resumir(carpeta_de_caso(datos, carpeta.name))
        except ErrorDeDatos as e:
            if _coincide(filtro, [carpeta.name]):
                con_error.append(
                    CasoConError(
                        caso=carpeta.name, error=f"{e.archivo.name}: {'; '.join(e.problemas)}"
                    )
                )
            continue
        if _coincide(filtro, [resumen.caso, resumen.cliente, resumen.pais, resumen.pais_nombre]):
            casos.append(resumen)
    return ListadoCasos(filtro=filtro, casos=casos, casos_con_error=con_error)


def _resumir(carpeta: Path) -> ResumenCaso:
    solicitud = _solicitud_coherente(carpeta)
    return ResumenCaso(
        caso=solicitud.id,
        cliente=solicitud.cliente,
        pais=solicitud.pais,
        pais_nombre=NOMBRES_PAIS[solicitud.pais],
        formato=solicitud.formato,
        fecha=solicitud.fecha,
    )


def _coincide(filtro: str | None, textos: list[str]) -> bool:
    """True si TODAS las palabras del filtro aparecen en alguno de los textos.

    Sin filtro (o con un filtro vacío) todo coincide. Se compara normalizado: sin
    mayúsculas ni tildes ("panama" encuentra "Panamá").
    """
    buscadas = palabras(filtro or "")
    disponibles = [p for texto in textos for p in palabras(texto)]
    return all(_palabra_coincide(buscada, disponibles) for buscada in buscadas)


def _palabra_coincide(buscada: str, disponibles: list[str]) -> bool:
    if len(buscada) < LARGO_MINIMO_PARA_PREFIJO:
        return buscada in disponibles
    return any(p.startswith(buscada) for p in disponibles)


# ---------- Lectura ----------


class CampoSolicitado(_Modelo):
    """Un campo que pide el cliente, con la misma forma para Excel, PDF y portal.

    - Excel: trae `hoja`, `celda_etiqueta` (donde va la etiqueta) y `celda` (donde va
      el valor). La plantilla no dice si el
      campo es obligatorio, así que `obligatorio` queda en None: no se inventa.
    - PDF y portal: traen `obligatorio`, y no tienen hoja ni celda.
    """

    etiqueta: str
    obligatorio: bool | None
    hoja: str | None = None
    celda_etiqueta: str | None = None  # Paso 7: el formulario Excel escribe también la etiqueta
    celda: str | None = None


class CasoLeido(_Modelo):
    """Lo que pide un caso. A propósito NO incluye el cuerpo del correo (ver `leer_caso`)."""

    caso: str
    cliente: str
    pais: Pais
    pais_nombre: str
    formato: Formato
    fecha: date
    campos: list[CampoSolicitado]
    soportes: list[TipoSoporte]
    avisos: list[str]  # cosas que la analista debe saber, en lenguaje claro


def leer_caso(datos: Path, caso: str) -> CasoLeido:
    """Lee la solicitud, la plantilla y los soportes exigidos de un caso.

    Lanza `ErrorDeCaso` si el caso no existe y `ErrorDeDatos` si un archivo está roto.

    El cuerpo del correo NO se devuelve: es contenido externo y podría traer
    instrucciones maliciosas para el modelo (principio 5). Lo que el agente necesita
    (país, formato, campos y soportes) ya está aquí, extraído de forma determinista.
    """
    carpeta = carpeta_de_caso(datos, caso)
    solicitud = _solicitud_coherente(carpeta)
    soportes = cargar_soportes_exigidos(carpeta)
    campos, avisos = _campos_y_avisos(carpeta, solicitud.formato)
    return CasoLeido(
        caso=solicitud.id,
        cliente=solicitud.cliente,
        pais=solicitud.pais,
        pais_nombre=NOMBRES_PAIS[solicitud.pais],
        formato=solicitud.formato,
        fecha=solicitud.fecha,
        campos=campos,
        soportes=soportes,
        avisos=avisos,
    )


def _solicitud_coherente(carpeta: Path) -> Solicitud:
    """Carga la solicitud y comprueba que su `id` sea el nombre de la carpeta."""
    solicitud = cargar_solicitud(carpeta)
    if solicitud.id != carpeta.name:
        raise ErrorDeDatos(
            carpeta / ARCHIVO_SOLICITUD,
            [f"el id «{solicitud.id}» no coincide con el nombre de la carpeta «{carpeta.name}»"],
        )
    return solicitud


def _campos_y_avisos(carpeta: Path, formato: Formato) -> tuple[list[CampoSolicitado], list[str]]:
    """Los campos según el formato, convertidos a `CampoSolicitado`, y los avisos que apliquen."""
    if formato is Formato.EXCEL:
        celdas = cargar_plantilla_celdas(carpeta)
        return [
            CampoSolicitado(
                etiqueta=c.etiqueta,
                obligatorio=None,
                hoja=c.hoja,
                celda_etiqueta=c.celda_etiqueta,
                celda=c.celda_valor,
            )
            for c in celdas
        ], []
    if formato is Formato.PDF:
        return _campos_de_plantilla(carpeta), []
    # Portal: la plantilla de campos es opcional.
    if not (carpeta / ARCHIVO_PLANTILLA_CAMPOS).exists():
        return [], [AVISO_PORTAL, AVISO_PORTAL_SIN_CAMPOS]
    return _campos_de_plantilla(carpeta), [AVISO_PORTAL]


def _campos_de_plantilla(carpeta: Path) -> list[CampoSolicitado]:
    return [
        CampoSolicitado(etiqueta=c.etiqueta, obligatorio=c.obligatorio)
        for c in cargar_plantilla_campos(carpeta)
    ]
