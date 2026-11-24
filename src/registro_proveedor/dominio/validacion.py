"""Validación de todos los insumos de `datos/`, con un reporte de errores y sugerencias.

- **Error**: el dato está roto y no se puede procesar. Hace fallar el CI.
- **Sugerencia**: el dato funciona, pero le falta algo que el diseño espera. Va para
  el dueño del dato y no hace fallar el CI.

Solo lee: `datos/` nunca se modifica. Un caso con errores no impide revisar los demás.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial
from pathlib import Path

from pydantic import BaseModel

from registro_proveedor.dominio.lectura import (
    ARCHIVO_GLOSARIO,
    ARCHIVO_INDICE_SOPORTES,
    ARCHIVO_MAESTRO,
    ARCHIVO_PLANTILLA_CAMPOS,
    ARCHIVO_PLANTILLA_CELDAS,
    ARCHIVO_SOLICITUD,
    CARPETA_CASOS,
    CARPETA_SOPORTES,
    ErrorDeDatos,
    cargar_glosario,
    cargar_indice_soportes,
    cargar_maestro,
    cargar_plantilla_campos,
    cargar_plantilla_celdas,
    cargar_solicitud,
    cargar_soportes_exigidos,
    carpeta_de_caso,
)
from registro_proveedor.dominio.modelos import CeldaPlantilla, Formato, Maestro


class Nivel(StrEnum):
    ERROR = "error"
    SUGERENCIA = "sugerencia"


@dataclass(frozen=True)
class Hallazgo:
    nivel: Nivel
    archivo: str  # ruta legible, relativa a la carpeta que contiene `datos/`
    mensaje: str


@dataclass
class Reporte:
    datos: Path
    hallazgos: list[Hallazgo] = field(default_factory=list)

    @property
    def errores(self) -> list[Hallazgo]:
        return [h for h in self.hallazgos if h.nivel is Nivel.ERROR]

    @property
    def sugerencias(self) -> list[Hallazgo]:
        return [h for h in self.hallazgos if h.nivel is Nivel.SUGERENCIA]

    @property
    def ok(self) -> bool:
        """True si no hay errores. Las sugerencias no cuentan."""
        return not self.errores

    def error(self, archivo: Path, mensaje: str) -> None:
        self.hallazgos.append(Hallazgo(Nivel.ERROR, self._legible(archivo), mensaje))

    def sugerencia(self, archivo: Path, mensaje: str) -> None:
        self.hallazgos.append(Hallazgo(Nivel.SUGERENCIA, self._legible(archivo), mensaje))

    def _legible(self, archivo: Path) -> str:
        base = self.datos.resolve().parent
        try:
            return archivo.resolve().relative_to(base).as_posix()
        except ValueError:
            return archivo.as_posix()


# ---------- Punto de entrada ----------


def validar_datos(datos: Path) -> Reporte:
    """Revisa todos los insumos de `datos/` y devuelve el reporte."""
    reporte = Reporte(datos=datos)
    if not datos.is_dir():
        reporte.error(datos, "no existe la carpeta de datos")
        return reporte
    maestro = _validar_maestro(datos, reporte)
    _validar_soportes(datos, reporte)
    _validar_glosario(datos, maestro, reporte)
    _validar_casos(datos, reporte)
    return reporte


def formatear_reporte(reporte: Reporte) -> str:
    """Texto del reporte para mostrar en la terminal."""
    lineas = [f"Validación de {reporte.datos.resolve().name}/", ""]
    for titulo, grupo in (("ERRORES", reporte.errores), ("SUGERENCIAS", reporte.sugerencias)):
        lineas.append(f"{titulo} ({len(grupo)})")
        lineas.extend(f"  · {h.archivo}: {h.mensaje}" for h in grupo)
        lineas.append("")
    estado = "OK" if reporte.ok else "CON ERRORES"
    lineas.append(
        f"Resultado: {estado} · {_contar(len(reporte.errores), 'error', 'errores')} · "
        f"{_contar(len(reporte.sugerencias), 'sugerencia', 'sugerencias')}"
    )
    return "\n".join(lineas)


def _contar(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


# ---------- Maestro ----------


def _validar_maestro(datos: Path, reporte: Reporte) -> Maestro | None:
    maestro = _intentar(reporte, lambda: cargar_maestro(datos))
    if maestro is None:
        return None
    archivo = datos / ARCHIVO_MAESTRO
    faltantes = _campos_vacios(maestro)
    if faltantes:
        reporte.sugerencia(
            archivo,
            "el maestro no tiene estos campos conocidos: "
            + ", ".join(faltantes)
            + ". Los formularios que los pidan quedarán con el campo faltante. "
            + _nota_version(faltantes),
        )
    for ruta in _campos_desconocidos(maestro):
        reporte.sugerencia(
            archivo,
            f"el campo «{ruta}» no está en el modelo del maestro: se acepta, pero revise "
            "si está bien escrito o si se debe agregar al modelo",
        )
    return maestro


def _nota_version(faltantes: list[str]) -> str:
    if "version" in faltantes or "actualizado_en" in faltantes:
        return (
            "Se recomienda agregar «version» y «actualizado_en» para que cada paquete "
            "registre con qué versión del maestro se generó."
        )
    return ""


def _campos_vacios(modelo: BaseModel, prefijo: str = "") -> list[str]:
    """Campos conocidos del modelo que no tienen valor (recorre los submodelos)."""
    vacios: list[str] = []
    for nombre in type(modelo).model_fields:
        valor = getattr(modelo, nombre)
        ruta = f"{prefijo}{nombre}"
        if valor is None:
            vacios.append(ruta)
        elif isinstance(valor, BaseModel):
            vacios.extend(_campos_vacios(valor, f"{ruta}."))
    return vacios


def _campos_desconocidos(modelo: BaseModel, prefijo: str = "") -> list[str]:
    """Campos que vienen en el JSON pero no están en el modelo (recorre los submodelos)."""
    desconocidos = [f"{prefijo}{nombre}" for nombre in (modelo.model_extra or {})]
    for nombre in type(modelo).model_fields:
        valor = getattr(modelo, nombre)
        if isinstance(valor, BaseModel):
            desconocidos.extend(_campos_desconocidos(valor, f"{prefijo}{nombre}."))
    return desconocidos


# ---------- Soportes ----------


def _validar_soportes(datos: Path, reporte: Reporte) -> None:
    soportes = _intentar(reporte, lambda: cargar_indice_soportes(datos))
    if soportes is None:
        return
    indice = datos / ARCHIVO_INDICE_SOPORTES
    carpeta = datos / CARPETA_SOPORTES
    tipos_vistos: set[str] = set()
    for i, soporte in enumerate(soportes, start=1):
        if soporte.tipo in tipos_vistos:
            reporte.error(
                indice,
                f"elemento {i}: el tipo «{soporte.tipo}» está repetido; no se sabría cuál usar",
            )
        tipos_vistos.add(soporte.tipo)
        if not (carpeta / soporte.archivo).is_file():
            reporte.error(indice, f"elemento {i}: no existe el archivo «{soporte.archivo}»")
    referenciados = {s.archivo for s in soportes} | {indice.name}
    presentes = sorted(p.name for p in carpeta.iterdir() if p.is_file()) if carpeta.is_dir() else []
    for archivo in presentes:
        if archivo not in referenciados:
            reporte.sugerencia(
                carpeta / archivo,
                "el archivo no está en index.json, así que nunca se usará",
            )


# ---------- Glosario ----------


def _validar_glosario(datos: Path, maestro: Maestro | None, reporte: Reporte) -> None:
    glosario = _intentar(reporte, lambda: cargar_glosario(datos))
    if glosario is None or maestro is None:
        return
    contenido = maestro.model_dump(mode="json")
    for etiqueta, ruta in glosario.items():
        problema = _problema_de_ruta(contenido, ruta)
        if problema:
            reporte.error(datos / ARCHIVO_GLOSARIO, f"«{etiqueta}» → «{ruta}»: {problema}")


def _problema_de_ruta(contenido: dict[str, object], ruta: str) -> str | None:
    """None si la ruta existe en el maestro; si no, la explicación del problema.

    Un campo conocido pero vacío no es un problema aquí: el mapeo lo dejará
    `faltante` y la validación del maestro ya lo sugiere.
    """
    actual: object = contenido
    recorrido: list[str] = []
    for parte in ruta.split("."):
        if not isinstance(actual, dict):
            return f"«{'.'.join(recorrido)}» es un valor, no un grupo"
        if parte not in actual:
            return f"no existe «{parte}» en el maestro" + (
                f" dentro de «{'.'.join(recorrido)}»" if recorrido else ""
            )
        actual = actual[parte]
        recorrido.append(parte)
        if actual is None:
            return None
    if isinstance(actual, dict):
        return "apunta a un grupo de datos, no a un valor"
    return None


# ---------- Casos ----------


def _validar_casos(datos: Path, reporte: Reporte) -> None:
    carpeta_casos = datos / CARPETA_CASOS
    if not carpeta_casos.is_dir():
        reporte.error(carpeta_casos, "no existe la carpeta de casos")
        return
    for carpeta in sorted(p for p in carpeta_casos.iterdir() if p.is_dir()):
        caso = _intentar(reporte, partial(carpeta_de_caso, datos, carpeta.name))
        if caso is not None:
            _validar_caso(caso, reporte)


def _validar_caso(carpeta: Path, reporte: Reporte) -> None:
    solicitud = _intentar(reporte, lambda: cargar_solicitud(carpeta))
    _intentar(reporte, lambda: cargar_soportes_exigidos(carpeta))
    if solicitud is None:
        return
    if solicitud.id != carpeta.name:
        reporte.error(
            carpeta / ARCHIVO_SOLICITUD,
            f"el id «{solicitud.id}» no coincide con el nombre de la carpeta «{carpeta.name}»",
        )
    celdas = carpeta / ARCHIVO_PLANTILLA_CELDAS
    campos = carpeta / ARCHIVO_PLANTILLA_CAMPOS
    if solicitud.formato is Formato.EXCEL:
        _validar_plantilla_excel(carpeta, reporte)
    elif solicitud.formato is Formato.PDF or campos.exists():
        # En PDF es obligatoria (si falta, la carga da el error); en portal, opcional.
        _intentar(reporte, lambda: cargar_plantilla_campos(carpeta))
    else:
        reporte.sugerencia(
            carpeta,
            "el caso es de portal y no tiene plantilla-campos.json: "
            "valores-portal.md no sabrá qué campos incluir",
        )
    sobrante = campos if solicitud.formato is Formato.EXCEL else celdas
    if sobrante.exists():
        reporte.sugerencia(
            sobrante, f"el caso es de formato «{solicitud.formato}», así que este archivo se ignora"
        )


def _validar_plantilla_excel(carpeta: Path, reporte: Reporte) -> None:
    celdas = _intentar(reporte, lambda: cargar_plantilla_celdas(carpeta))
    if celdas is not None:
        for mensaje in _celdas_repetidas(celdas):
            reporte.error(carpeta / ARCHIVO_PLANTILLA_CELDAS, mensaje)


def _celdas_repetidas(celdas: list[CeldaPlantilla]) -> list[str]:
    """Dos elementos no pueden escribir en la misma celda de la misma hoja."""
    usadas: dict[tuple[str, str], str] = {}
    problemas: list[str] = []
    for i, elemento in enumerate(celdas, start=1):
        for celda, uso in ((elemento.celda_etiqueta, "etiqueta"), (elemento.celda_valor, "valor")):
            clave = (elemento.hoja, celda)
            if clave in usadas:
                problemas.append(
                    f"elemento {i}: la celda {celda} de la hoja «{elemento.hoja}» "
                    f"ya la usa el {usadas[clave]}"
                )
            else:
                usadas[clave] = f"elemento {i} ({uso})"
    return problemas


# ---------- Utilidad ----------


def _intentar[T](reporte: Reporte, carga: Callable[[], T]) -> T | None:
    """Ejecuta una carga; si falla, anota cada problema como error y devuelve None."""
    try:
        return carga()
    except ErrorDeDatos as e:
        for problema in e.problemas:
            reporte.error(e.archivo, problema)
        return None
