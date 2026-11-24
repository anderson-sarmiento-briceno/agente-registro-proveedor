"""Validación de todos los insumos de `datos/`, con un reporte de errores y sugerencias.

¿Qué agrega a `lectura.py`?
    `lectura.py` revisa cada archivo por separado: que tenga la forma de su modelo.
    Aquí se revisa lo que solo se ve mirando varios archivos juntos:
    - que el `id` de la solicitud coincida con el nombre de su carpeta,
    - que cada formato tenga su plantilla (Excel → celdas; PDF → campos),
    - que dos elementos de una plantilla no escriban en la misma celda,
    - que cada ruta del glosario exista en el maestro,
    - que cada soporte del índice tenga su archivo, y que no haya tipos repetidos.

Dos niveles de hallazgo:
    - **Error**: el dato está roto y no se puede procesar. Hace fallar el CI.
    - **Sugerencia**: el dato funciona, pero le falta algo que el diseño espera
      (por ejemplo, el maestro sin `version`). Va para el dueño del dato y no hace
      fallar el CI.

Dos reglas:
    - Solo lee: `datos/` nunca se modifica. Lo que falta se reporta, no se "arregla".
    - Un archivo o un caso con errores no impide revisar los demás: se anota el
      problema y se sigue. Al final se ven todos los problemas de una vez.

Lo que NO se revisa aquí (a propósito):
    - Si las etiquetas de las plantillas están en el glosario → es el mapeo (Paso 5).
    - Si los soportes están vencidos o si falta uno exigido → son las reglas y el
      checklist (Pasos 6 y 8). Que al caso de Ecuador le falte un soporte no es un
      dato roto: es justo lo que ese caso pone a prueba.
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

# ---------- El reporte ----------
# Se usan `dataclass` (de Python) y no modelos de Pydantic porque aquí no hay nada
# que validar: son datos que crea nuestro propio código, no datos que vienen de fuera.


class Nivel(StrEnum):
    ERROR = "error"
    SUGERENCIA = "sugerencia"


@dataclass(frozen=True)
class Hallazgo:
    """Un problema encontrado: qué tan grave es, en qué archivo y qué pasa."""

    nivel: Nivel
    archivo: str  # ruta corta y legible, como "datos/repositorio/maestro.json"
    mensaje: str


@dataclass
class Reporte:
    """Acumula los hallazgos mientras se revisan los datos."""

    datos: Path
    hallazgos: list[Hallazgo] = field(default_factory=list)

    # `@property` permite usar `reporte.errores` como si fuera un atributo, aunque
    # en realidad se calcula cada vez a partir de `hallazgos`.
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
        """Ruta relativa a la carpeta que contiene `datos/`, para no mostrar rutas largas.

        "C:/Users/.../Agente_registro_Proveedor/datos/repositorio/maestro.json"
        se muestra como "datos/repositorio/maestro.json".
        """
        base = self.datos.resolve().parent
        try:
            return archivo.resolve().relative_to(base).as_posix()
        except ValueError:  # el archivo está fuera de esa carpeta: se muestra completo
            return archivo.as_posix()


# ---------- Punto de entrada ----------


def validar_datos(datos: Path) -> Reporte:
    """Revisa todos los insumos de `datos/` y devuelve el reporte.

    El orden importa: el maestro se carga primero porque el glosario se revisa
    contra él. Si el maestro está roto, las rutas del glosario no se pueden revisar,
    pero todo lo demás sí.
    """
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
    """Texto del reporte para mostrar en la terminal: errores, sugerencias y resumen."""
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
    """Escribe la cantidad con su palabra en singular o plural: "1 error", "2 errores"."""
    return f"{n} {singular if n == 1 else plural}"


# ---------- Maestro ----------


def _validar_maestro(datos: Path, reporte: Reporte) -> Maestro | None:
    """Carga el maestro y sugiere completar lo que falta o revisar lo desconocido.

    Devuelve el maestro (o None si está roto) porque el glosario lo necesita después.
    """
    maestro = _intentar(reporte, lambda: cargar_maestro(datos))
    if maestro is None:
        return None
    archivo = datos / ARCHIVO_MAESTRO
    # Una sola sugerencia con todos los campos vacíos, para no llenar el reporte.
    faltantes = _campos_vacios(maestro)
    if faltantes:
        reporte.sugerencia(
            archivo,
            "el maestro no tiene estos campos conocidos: "
            + ", ".join(faltantes)
            + ". Los formularios que los pidan quedarán con el campo faltante. "
            + _nota_version(faltantes),
        )
    # Una sugerencia por cada campo desconocido: cada uno requiere una decisión.
    for ruta in _campos_desconocidos(maestro):
        reporte.sugerencia(
            archivo,
            f"el campo «{ruta}» no está en el modelo del maestro: se acepta, pero revise "
            "si está bien escrito o si se debe agregar al modelo",
        )
    return maestro


def _nota_version(faltantes: list[str]) -> str:
    """Explicación extra cuando faltan los campos de versión (los usa el manifiesto, HU-7)."""
    if "version" in faltantes or "actualizado_en" in faltantes:
        return (
            "Se recomienda agregar «version» y «actualizado_en» para que cada paquete "
            "registre con qué versión del maestro se generó."
        )
    return ""


def _campos_vacios(modelo: BaseModel, prefijo: str = "") -> list[str]:
    """Campos conocidos del modelo que no tienen valor, con su ruta completa.

    Es recursiva: si un campo es a su vez un modelo (como `banco`), se llama a sí
    misma para revisarlo por dentro, con el prefijo "banco.". Así un `swift` vacío
    se reporta como "banco.swift". Si el grupo entero falta, se reporta solo "banco".
    """
    vacios: list[str] = []
    # `model_fields` es la lista de campos que declara la clase (no los del JSON).
    for nombre in type(modelo).model_fields:
        valor = getattr(modelo, nombre)
        ruta = f"{prefijo}{nombre}"
        if valor is None:
            vacios.append(ruta)
        elif isinstance(valor, BaseModel):
            vacios.extend(_campos_vacios(valor, f"{ruta}."))
    return vacios


def _campos_desconocidos(modelo: BaseModel, prefijo: str = "") -> list[str]:
    """Campos que vienen en el JSON pero no están en el modelo (recorre los submodelos).

    Pydantic guarda esos campos en `model_extra`, porque los modelos del maestro son
    tolerantes (`extra="allow"`).
    """
    desconocidos = [f"{prefijo}{nombre}" for nombre in (modelo.model_extra or {})]
    for nombre in type(modelo).model_fields:
        valor = getattr(modelo, nombre)
        if isinstance(valor, BaseModel):
            desconocidos.extend(_campos_desconocidos(valor, f"{prefijo}{nombre}."))
    return desconocidos


# ---------- Soportes ----------


def _validar_soportes(datos: Path, reporte: Reporte) -> None:
    """Revisa el índice de soportes contra los archivos que hay en la carpeta."""
    soportes = _intentar(reporte, lambda: cargar_indice_soportes(datos))
    if soportes is None:
        return
    indice = datos / ARCHIVO_INDICE_SOPORTES
    carpeta = datos / CARPETA_SOPORTES

    # 1. Cada tipo una sola vez: con dos "camara_comercio", el paquete no sabría cuál usar.
    # 2. Cada archivo debe existir: si no, el paquete no podría copiarlo.
    tipos_vistos: set[str] = set()
    for i, soporte in enumerate(soportes, start=1):  # start=1: se cuenta desde 1
        if soporte.tipo in tipos_vistos:
            reporte.error(
                indice,
                f"elemento {i}: el tipo «{soporte.tipo}» está repetido; no se sabría cuál usar",
            )
        tipos_vistos.add(soporte.tipo)
        if not (carpeta / soporte.archivo).is_file():
            reporte.error(indice, f"elemento {i}: no existe el archivo «{soporte.archivo}»")

    # 3. Al revés: un archivo en la carpeta que el índice no menciona nunca se usará.
    #    No es un error (no rompe nada), pero probablemente alguien olvidó registrarlo.
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
    """Comprueba que cada ruta del glosario apunte a un dato que existe en el maestro."""
    glosario = _intentar(reporte, lambda: cargar_glosario(datos))
    if glosario is None or maestro is None:
        return
    # El maestro se convierte en diccionario para recorrerlo por nombres.
    # `model_dump` incluye también los campos desconocidos (los de `model_extra`),
    # así que una ruta puede apuntar a un campo nuevo del maestro.
    contenido = maestro.model_dump(mode="json")
    for etiqueta, ruta in glosario.items():
        problema = _problema_de_ruta(contenido, ruta)
        if problema:
            reporte.error(datos / ARCHIVO_GLOSARIO, f"«{etiqueta}» → «{ruta}»: {problema}")


def _problema_de_ruta(contenido: dict[str, object], ruta: str) -> str | None:
    """None si la ruta existe en el maestro; si no, la explicación del problema.

    Recorre la ruta parte por parte. Para "banco.swift": entra a "banco" y, dentro,
    busca "swift". Los problemas posibles son:
    - una parte no existe ("banco.swiftt"),
    - se intenta entrar en un valor como si fuera un grupo ("nit.numero"),
    - la ruta termina en un grupo, no en un valor ("banco": no se puede escribir
      un grupo entero en una celda).

    Un campo conocido pero vacío (None) no es un problema aquí: el mapeo lo dejará
    `faltante` y la validación del maestro ya lo sugiere.
    Limitación: si un grupo entero está vacío (sin `banco`), no se puede revisar
    lo que hay dentro, así que un error de escritura como "banco.swiftt" no se detecta.
    """
    actual: object = contenido
    recorrido: list[str] = []  # partes ya recorridas, para el mensaje de error
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
    """Revisa cada carpeta de `datos/casos/`, en orden alfabético (así el reporte no cambia)."""
    carpeta_casos = datos / CARPETA_CASOS
    if not carpeta_casos.is_dir():
        reporte.error(carpeta_casos, "no existe la carpeta de casos")
        return
    for carpeta in sorted(p for p in carpeta_casos.iterdir() if p.is_dir()):
        # `partial(f, a, b)` crea una función sin argumentos que, al llamarla, ejecuta
        # f(a, b). Se usa en vez de `lambda` porque, dentro de un bucle, mypy no logra
        # deducir el tipo de la lambda.
        caso = _intentar(reporte, partial(carpeta_de_caso, datos, carpeta.name))
        if caso is not None:
            _validar_caso(caso, reporte)


def _validar_caso(carpeta: Path, reporte: Reporte) -> None:
    """Revisa los archivos de un caso según su formato."""
    solicitud = _intentar(reporte, lambda: cargar_solicitud(carpeta))
    # Los soportes exigidos se revisan aunque la solicitud esté rota: son independientes.
    _intentar(reporte, lambda: cargar_soportes_exigidos(carpeta))
    if solicitud is None:
        return  # sin solicitud no se sabe el formato, así que no se puede seguir

    if solicitud.id != carpeta.name:
        reporte.error(
            carpeta / ARCHIVO_SOLICITUD,
            f"el id «{solicitud.id}» no coincide con el nombre de la carpeta «{carpeta.name}»",
        )

    # Qué plantilla corresponde según el formato:
    #   xlsx   → plantilla-celdas.json (obligatoria)
    #   pdf    → plantilla-campos.json (obligatoria)
    #   portal → plantilla-campos.json (opcional; si falta, es solo una sugerencia)
    celdas = carpeta / ARCHIVO_PLANTILLA_CELDAS
    campos = carpeta / ARCHIVO_PLANTILLA_CAMPOS
    if solicitud.formato is Formato.EXCEL:
        _validar_plantilla_excel(carpeta, reporte)
    elif solicitud.formato is Formato.PDF or campos.exists():
        # En PDF, si el archivo falta, la carga misma da el error "no existe el archivo".
        _intentar(reporte, lambda: cargar_plantilla_campos(carpeta))
    else:
        reporte.sugerencia(
            carpeta,
            "el caso es de portal y no tiene plantilla-campos.json: "
            "valores-portal.md no sabrá qué campos incluir",
        )

    # La plantilla del otro tipo sobra y se ignorará. No rompe nada, pero se avisa
    # por si alguien se equivocó de formato en la solicitud.
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
    """Dos elementos no pueden escribir en la misma celda de la misma hoja.

    Si pasara, al generar el Excel (Paso 7) el segundo valor borraría al primero sin
    aviso. Se revisan juntas las celdas de etiqueta y las de valor, porque un valor
    tampoco puede caer encima de una etiqueta. La misma celda en hojas distintas sí
    está permitida (en el caso CO, "B3" se usa en las dos hojas).
    """
    # Clave: (hoja, celda). Valor: quién la usó primero, para el mensaje.
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
    """Ejecuta una carga; si falla, anota cada problema como error y devuelve None.

    Es lo que permite "anotar y seguir": en vez de que el primer archivo roto detenga
    toda la validación, el error queda en el reporte y quien llama decide qué hacer
    con el None (normalmente, saltar las revisiones que dependían de ese dato).

    `carga` es una función sin argumentos (una `lambda` o un `partial`) para que la
    lectura ocurra DENTRO del `try`. Si se pasara el resultado ya calculado, el
    error saltaría antes de llegar aquí.
    """
    try:
        return carga()
    except ErrorDeDatos as e:
        for problema in e.problemas:
            reporte.error(e.archivo, problema)
        return None
