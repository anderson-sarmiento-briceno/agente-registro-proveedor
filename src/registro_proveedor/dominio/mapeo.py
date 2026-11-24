"""Mapeo de campos: qué dato del maestro va en cada campo que pide el cliente.

Es el corazón del núcleo. Para cada campo del formulario ("Nombre de la empresa") se
busca su etiqueta en el glosario (→ "razon_social") y después el valor en el maestro
(→ "Empresa Ejemplo S.A.S."). Cada campo termina en uno de tres estados:

    lleno                  → se encontró el dato con suficiente seguridad.
    requiere_confirmacion  → hay una propuesta, pero con dudas: la analista decide.
    faltante               → no hay fuente en el maestro. Queda vacío (principio 2:
                             NUNCA se inventa un valor).

La búsqueda en el glosario va en capas, de la más segura a la menos segura:

    1. glosario_exacto       "Razón social" == "Razón social"            confianza 1.0
    2. glosario_normalizado  "RAZON SOCIAL:" ≈ "Razón social"            confianza 0.95
    3. similitud             "Razon socail" se parece a "Razón social"   confianza = puntaje
                             ≥ 0.9 → lleno · entre 0.8 y 0.9 → requiere_confirmacion
                             · menos de 0.8 → faltante
    (los números 0.95, 0.9 y 0.8 se leen de config/reglas.yaml)

Después de las capas se aplica la regla de país RN1: si el cliente no es de Colombia,
un campo lleno con el NIT pasa a requiere_confirmacion ("identificador extranjero").

Cada campo guarda de dónde salió (ruta), cómo se encontró (método), la confianza y
una nota en lenguaje claro: es la trazabilidad por valor (S12).

El mapeo completo se guarda en `out/<caso>/mapeo.json`, con los valores COMPLETOS:
es la fuente que usará el generador de formularios (Paso 7), de modo que el modelo
de lenguaje nunca "pasa" valores de una herramienta a otra (S6). Lo que se le
muestra al modelo sale enmascarado (eso lo hace la herramienta, no este módulo).
"""

import os
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
from rapidfuzz import fuzz, process

from registro_proveedor.dominio.casos import CampoSolicitado, CasoLeido
from registro_proveedor.dominio.lectura import ErrorDeDatos, describir_error_validacion, leer_json
from registro_proveedor.dominio.modelos import Glosario, Maestro, Pais
from registro_proveedor.dominio.reglas import (
    ReglaIdentificador,
    Reglas,
    ReglasMapeo,
    nota_identificador_extranjero,
)
from registro_proveedor.dominio.texto import normalizar

ARCHIVO_MAPEO = "mapeo.json"


class Estado(StrEnum):
    LLENO = "lleno"
    FALTANTE = "faltante"
    REQUIERE_CONFIRMACION = "requiere_confirmacion"


class Metodo(StrEnum):
    """Cómo se encontró la etiqueta en el glosario."""

    GLOSARIO_EXACTO = "glosario_exacto"
    GLOSARIO_NORMALIZADO = "glosario_normalizado"
    SIMILITUD = "similitud"
    SIN_COINCIDENCIA = "sin_coincidencia"  # nada se parece lo suficiente
    # "sugerencia_llm" (capa 4) llegará con el agente: siempre requiere confirmación.


class Decision(StrEnum):
    """Lo que la analista decide sobre un campo en `requiere_confirmacion`."""

    ACEPTAR = "aceptar"  # el campo pasa a `lleno` con el valor propuesto
    DEJAR_FALTANTE = "dejar_faltante"  # el campo queda vacío


class ErrorDeMapeo(Exception):
    """Un pedido sobre el mapeo que no se puede cumplir, con mensaje para la usuaria."""


# ---------- Modelos ----------


class _Modelo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Confirmacion(_Modelo):
    """Quién decidió qué sobre un campo, y cuándo (HU-2).

    `valor_propuesto` es el valor que se le mostró a la analista al decidir. Se guarda
    porque, si lo deja faltante, el campo ya no tiene valor; y hace falta para dos
    cosas: cambiar de opinión después y, al volver a mapear, comprobar que la
    propuesta sigue siendo la misma que ella decidió.
    """

    decision: Decision
    por: str
    en: datetime
    valor_propuesto: str


class CampoMapeado(_Modelo):
    """Un campo del formulario con su valor (o sin él) y toda su trazabilidad."""

    # Lo que pide el cliente (copiado de `CampoSolicitado`, para que el generador del
    # Paso 7 tenga todo en mapeo.json sin volver a leer la plantilla).
    etiqueta: str
    obligatorio: bool | None
    hoja: str | None
    celda: str | None

    # El resultado del mapeo.
    estado: Estado
    metodo: Metodo
    confianza: float  # 0.0 a 1.0
    etiqueta_glosario: str | None  # la etiqueta del glosario con la que coincidió
    ruta: str | None  # dónde está el dato en el maestro, como "banco.swift"
    valor: str | None  # el valor COMPLETO (sin enmascarar): solo vive en mapeo.json
    nota: str  # explicación para personas: por qué quedó en este estado
    confirmacion: Confirmacion | None = None

    @model_validator(mode="after")
    def _nunca_un_valor_sin_fuente(self) -> "CampoMapeado":
        """Garantía del principio 2, revisada cada vez que se crea un campo.

        - Si hay un valor, debe haber una ruta en el maestro (su fuente).
        - Un campo `faltante` no tiene valor.
        - Un campo `lleno` o `requiere_confirmacion` sí lo tiene.
        """
        if self.valor is not None and self.ruta is None:
            raise ValueError("un valor sin ruta en el maestro sería un valor inventado")
        if self.estado is Estado.FALTANTE and self.valor is not None:
            raise ValueError("un campo faltante no puede tener valor")
        if self.estado is not Estado.FALTANTE and self.valor is None:
            raise ValueError(f"un campo en estado «{self.estado}» necesita un valor")
        return self


class Mapeo(_Modelo):
    """El mapeo completo de un caso: lo que se guarda en `out/<caso>/mapeo.json`."""

    caso: str
    generado_en: datetime
    fecha_ejecucion: date  # RN7
    version_maestro: str | None  # None = el maestro no tiene versión (sugerencia del Paso 2)
    campos: list[CampoMapeado]

    def en_estado(self, estado: Estado) -> list[CampoMapeado]:
        return [c for c in self.campos if c.estado is estado]


# ---------- Capas 1 a 3: buscar la etiqueta en el glosario ----------


@dataclass(frozen=True)
class Coincidencia:
    """La mejor coincidencia de una etiqueta en el glosario."""

    metodo: Metodo
    confianza: float
    etiqueta_glosario: str
    ruta: str
    # Otra etiqueta del glosario, con OTRA ruta, que se parece igual de bien. Si existe,
    # no se puede decidir solo: el campo requiere confirmación.
    empate_con: str | None = None


def buscar_en_glosario(
    etiqueta: str, glosario: Glosario, reglas: ReglasMapeo
) -> Coincidencia | None:
    """Busca la etiqueta en el glosario por capas. None si el glosario está vacío.

    Devuelve la mejor coincidencia aunque sea mala (por ejemplo, 0.6): quien llama
    decide el estado con los umbrales, y la nota puede decir "lo más parecido fue...".
    """
    # Capa 1: exacta.
    if etiqueta in glosario:
        return Coincidencia(Metodo.GLOSARIO_EXACTO, 1.0, etiqueta, glosario[etiqueta])

    # Capa 2: igual después de normalizar. `indice` va de la versión normalizada a la
    # etiqueta original del glosario. Se recorre en orden alfabético para que, si dos
    # etiquetas normalizan igual, siempre gane la misma (la validación lo reporta).
    indice: dict[str, str] = {}
    for clave in sorted(glosario):
        indice.setdefault(normalizar(clave), clave)
    buscada = normalizar(etiqueta)
    if buscada in indice:
        original = indice[buscada]
        return Coincidencia(
            Metodo.GLOSARIO_NORMALIZADO, reglas.confianza_normalizado, original, glosario[original]
        )

    # Capa 3: la más parecida. `token_sort_ratio` ordena las palabras antes de comparar
    # ("social razón" = "razón social") pero compara las frases COMPLETAS. No se usa
    # `token_set_ratio` porque daría 100 % entre "Cédula del representante legal" y
    # "Representante legal" (una contiene a la otra) y llenaría la cédula con el nombre.
    candidatos = process.extract(buscada, list(indice), scorer=fuzz.token_sort_ratio, limit=2)
    if not candidatos:
        return None
    (mejor, puntaje, _), *resto = candidatos
    original = indice[mejor]
    empate = None
    if resto and resto[0][1] == puntaje and glosario[indice[resto[0][0]]] != glosario[original]:
        empate = indice[resto[0][0]]
    return Coincidencia(Metodo.SIMILITUD, puntaje / 100, original, glosario[original], empate)


# ---------- Buscar el valor en el maestro ----------


def valor_en_maestro(contenido: dict[str, object], ruta: str) -> str | None:
    """El valor de una ruta del maestro, como texto. None si no existe o está vacío.

    `contenido` es el maestro convertido a diccionario (`model_dump(mode="json")`), así
    que las fechas ya son "2008-03-14" y los números grandes ya son texto.
    """
    actual: object = contenido
    for parte in ruta.split("."):
        if not isinstance(actual, dict) or parte not in actual:
            return None
        actual = actual[parte]
    if actual is None or isinstance(actual, dict | list):
        return None  # vacío, o un grupo/lista: no es un valor para una celda
    if isinstance(actual, bool):
        return "Sí" if actual else "No"
    return str(actual)


# ---------- Mapear ----------


def mapear_campo(
    campo: CampoSolicitado, glosario: Glosario, contenido: dict[str, object], reglas: ReglasMapeo
) -> CampoMapeado:
    """Mapea un campo: busca la etiqueta en el glosario y el valor en el maestro."""
    coincidencia = buscar_en_glosario(campo.etiqueta, glosario, reglas)

    # Sin coincidencia suficiente: faltante, sin ruta ni valor.
    if coincidencia is None or coincidencia.confianza < reglas.umbral_confirmar:
        nota = "la etiqueta no está en el glosario"
        if coincidencia is not None:
            nota += (
                f" (lo más parecido fue «{coincidencia.etiqueta_glosario}», "
                f"{coincidencia.confianza:.0%}, menos del mínimo de {reglas.umbral_confirmar:.0%})"
            )
        return _campo(
            campo,
            Estado.FALTANTE,
            None,
            nota,
            metodo=Metodo.SIN_COINCIDENCIA,
            confianza=coincidencia.confianza if coincidencia else 0.0,
        )

    # Hay coincidencia: se busca el valor en el maestro.
    valor = valor_en_maestro(contenido, coincidencia.ruta)
    if valor is None:
        nota = f"el maestro no tiene el dato «{coincidencia.ruta}»"
        return _campo(campo, Estado.FALTANTE, None, nota, coincidencia=coincidencia)
    estado, nota = _estado_y_nota(coincidencia, reglas.umbral_lleno)
    return _campo(campo, estado, valor, nota, coincidencia=coincidencia)


def _campo(
    campo: CampoSolicitado,
    estado: Estado,
    valor: str | None,
    nota: str,
    *,
    coincidencia: Coincidencia | None = None,
    metodo: Metodo = Metodo.SIN_COINCIDENCIA,
    confianza: float = 0.0,
) -> CampoMapeado:
    """Arma un `CampoMapeado` con los datos del campo pedido y, si hay, los de la coincidencia."""
    return CampoMapeado(
        etiqueta=campo.etiqueta,
        obligatorio=campo.obligatorio,
        hoja=campo.hoja,
        celda=campo.celda,
        estado=estado,
        metodo=coincidencia.metodo if coincidencia else metodo,
        confianza=coincidencia.confianza if coincidencia else confianza,
        etiqueta_glosario=coincidencia.etiqueta_glosario if coincidencia else None,
        ruta=coincidencia.ruta if coincidencia else None,
        valor=valor,
        nota=nota,
    )


def _estado_y_nota(c: Coincidencia, umbral_lleno: float) -> tuple[Estado, str]:
    if c.metodo is Metodo.GLOSARIO_EXACTO:
        return Estado.LLENO, f"igual a la etiqueta «{c.etiqueta_glosario}» del glosario"
    if c.metodo is Metodo.GLOSARIO_NORMALIZADO:
        return Estado.LLENO, (
            f"igual a «{c.etiqueta_glosario}» del glosario sin contar mayúsculas, tildes ni signos"
        )
    parecido = f"parecida a «{c.etiqueta_glosario}» del glosario ({c.confianza:.0%})"
    if c.empate_con is not None:
        return Estado.REQUIERE_CONFIRMACION, (
            f"{parecido}, pero también a «{c.empate_con}», que es otro dato: confirme cuál es"
        )
    if c.confianza >= umbral_lleno:
        return Estado.LLENO, parecido
    return Estado.REQUIERE_CONFIRMACION, f"{parecido}: confirme que es el mismo dato"


def mapear_caso(
    caso: CasoLeido,
    glosario: Glosario,
    maestro: Maestro,
    reglas: Reglas,
    generado_en: datetime,
    fecha_ejecucion: date,
    anterior: Mapeo | None = None,
) -> Mapeo:
    """Mapea todos los campos de un caso, conservando las confirmaciones de `anterior`.

    El orden importa:
    1. las tres capas (`mapear_campo`);
    2. la regla de país RN1, que puede bajar un campo `lleno` a `requiere_confirmacion`;
    3. las confirmaciones anteriores. Van al final para que, si la analista ya aceptó el
       NIT como RUC, al volver a mapear su decisión se conserve.

    Si la analista ya confirmó un campo y se vuelve a mapear, su decisión se conserva,
    siempre que la propuesta sea la misma (misma ruta y mismo valor). Si el maestro
    cambió, la decisión anterior ya no aplica y hay que volver a confirmar.
    """
    contenido = maestro.model_dump(mode="json")
    campos = [
        aplicar_identificador(
            mapear_campo(c, glosario, contenido, reglas.mapeo),
            caso.pais,
            reglas.identificador_tributario,
        )
        for c in caso.campos
    ]
    if anterior is not None:
        campos = [_conservar_confirmacion(c, anterior) for c in campos]
    return Mapeo(
        caso=caso.caso,
        generado_en=generado_en,
        fecha_ejecucion=fecha_ejecucion,
        version_maestro=maestro.version,
        campos=campos,
    )


def aplicar_identificador(
    campo: CampoMapeado, pais_cliente: Pais, regla: ReglaIdentificador
) -> CampoMapeado:
    """RN1: un campo con el NIT, para un cliente de otro país, requiere confirmación.

    Aplica a cualquier etiqueta que haya terminado en el NIT ("RUC", "RTN",
    "Identificación tributaria"...), porque lo que importa es el DATO, no el nombre.
    Un campo faltante no cambia: no hay valor que confirmar.
    """
    nota = nota_identificador_extranjero(regla, pais_cliente)
    if nota is None or campo.ruta != regla.ruta_maestro or campo.estado is Estado.FALTANTE:
        return campo
    return campo.model_copy(
        update={"estado": Estado.REQUIERE_CONFIRMACION, "nota": f"{campo.nota} · {nota}"}
    )


def _conservar_confirmacion(campo: CampoMapeado, anterior: Mapeo) -> CampoMapeado:
    """Si el campo ya se había confirmado con la MISMA propuesta, se le aplica esa decisión."""
    if campo.estado is not Estado.REQUIERE_CONFIRMACION:
        return campo
    previo = next((c for c in anterior.campos if c.etiqueta == campo.etiqueta), None)
    if previo is None or previo.confirmacion is None:
        return campo
    misma_propuesta = (
        previo.ruta == campo.ruta and previo.confirmacion.valor_propuesto == campo.valor
    )
    return _aplicar(campo, previo.confirmacion) if misma_propuesta else campo


# ---------- Confirmar ----------


def confirmar_campo(
    mapeo: Mapeo, etiqueta: str, decision: Decision, por: str, en: datetime
) -> tuple[Mapeo, CampoMapeado]:
    """Aplica la decisión de la analista a UN campo. Los demás quedan iguales.

    Se puede confirmar un campo en `requiere_confirmacion`, o cambiar de opinión sobre
    uno ya confirmado. Un campo `lleno` o `faltante` por sí solo no se confirma: no hay
    nada que decidir. Devuelve el mapeo nuevo y el campo actualizado.
    """
    indice = _buscar_etiqueta(mapeo, etiqueta)
    propuesta = _propuesta(mapeo.campos[indice], mapeo)
    confirmacion = Confirmacion(
        decision=decision, por=por, en=en, valor_propuesto=_valor_de(propuesta)
    )
    actualizado = _aplicar(propuesta, confirmacion)
    campos = list(mapeo.campos)
    campos[indice] = actualizado
    return mapeo.model_copy(update={"campos": campos}), actualizado


def _propuesta(campo: CampoMapeado, mapeo: Mapeo) -> CampoMapeado:
    """El campo tal como estaba ANTES de decidir (en `requiere_confirmacion`).

    - Si todavía no se ha decidido, es el campo mismo.
    - Si ya se decidió (la analista cambia de opinión), se reconstruye con el valor
      propuesto guardado en la confirmación anterior.
    - Si es un campo `lleno` o `faltante` sin confirmación, no hay nada que decidir.
    """
    if campo.estado is Estado.REQUIERE_CONFIRMACION:
        return campo
    if campo.confirmacion is None:
        raise ErrorDeMapeo(
            f"el campo «{campo.etiqueta}» está «{campo.estado}»: solo se confirman los campos "
            f"en requiere_confirmacion. Pendientes: {_pendientes(mapeo)}"
        )
    return campo.model_copy(
        update={
            "estado": Estado.REQUIERE_CONFIRMACION,
            "valor": campo.confirmacion.valor_propuesto,
            "confirmacion": None,
        }
    )


def _valor_de(campo: CampoMapeado) -> str:
    # Un campo en requiere_confirmacion siempre tiene valor (lo garantiza el validador).
    assert campo.valor is not None
    return campo.valor


def _buscar_etiqueta(mapeo: Mapeo, etiqueta: str) -> int:
    """Posición del campo: primero exacta y, si no, sin mayúsculas ni tildes (si es única)."""
    for i, campo in enumerate(mapeo.campos):
        if campo.etiqueta == etiqueta:
            return i
    parecidos = [
        i for i, c in enumerate(mapeo.campos) if normalizar(c.etiqueta) == normalizar(etiqueta)
    ]
    if len(parecidos) == 1:
        return parecidos[0]
    raise ErrorDeMapeo(f"no hay un campo «{etiqueta}» en el caso. Pendientes: {_pendientes(mapeo)}")


def _pendientes(mapeo: Mapeo) -> str:
    nombres = [f"«{c.etiqueta}»" for c in mapeo.en_estado(Estado.REQUIERE_CONFIRMACION)]
    return ", ".join(nombres) or "ninguno"


def _aplicar(campo: CampoMapeado, confirmacion: Confirmacion) -> CampoMapeado:
    """Aplica una confirmación a un campo en `requiere_confirmacion`.

    La nota NO se modifica: sigue explicando por qué el campo necesitaba confirmación.
    Quién decidió qué y cuándo queda en `confirmacion`.
    """
    if confirmacion.decision is Decision.ACEPTAR:
        return campo.model_copy(update={"estado": Estado.LLENO, "confirmacion": confirmacion})
    return campo.model_copy(
        update={"estado": Estado.FALTANTE, "valor": None, "confirmacion": confirmacion}
    )


# ---------- Guardar y leer mapeo.json ----------


def guardar_mapeo(carpeta: Path, mapeo: Mapeo) -> Path:
    """Escribe `mapeo.json` en la carpeta del caso (en `out/`) y devuelve su ruta.

    Se escribe primero en un archivo temporal y después se reemplaza el definitivo
    (`os.replace` es atómico): si algo falla a mitad de camino, el mapeo anterior
    queda intacto en vez de quedar un archivo a medio escribir.
    """
    destino = carpeta / ARCHIVO_MAPEO
    temporal = carpeta / f".{ARCHIVO_MAPEO}.tmp"
    temporal.write_text(mapeo.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporal, destino)
    return destino


def cargar_mapeo(carpeta: Path) -> Mapeo | None:
    """Lee `mapeo.json` de la carpeta del caso. None si todavía no existe.

    Lanza `ErrorDeDatos` si el archivo existe pero está dañado.
    """
    ruta = carpeta / ARCHIVO_MAPEO
    if not ruta.exists():
        return None
    contenido = leer_json(ruta)
    try:
        return Mapeo.model_validate(contenido)
    except ValidationError as e:
        raise ErrorDeDatos(ruta, [describir_error_validacion(err) for err in e.errors()]) from None
