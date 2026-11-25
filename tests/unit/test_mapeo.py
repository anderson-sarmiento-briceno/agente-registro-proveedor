"""Pruebas de `dominio/mapeo.py`: capas del mapeo, regla de país, confirmación y mapeo.json.

Cómo está organizado:
    1. Los 4 casos de referencia y la garantía principal: NINGÚN valor sale de algo
       distinto del maestro (principio 2).
    2. Cada capa: exacta, normalizada, parecida (llena, por confirmar o faltante).
    3. La regla de país RN1 (Paso 6).
    4. Cómo se convierte cada tipo de valor del maestro en texto.
    5. Confirmar un campo, cambiar de opinión y conservar decisiones al volver a mapear.
    6. Guardar y leer mapeo.json.

`_mapear("Etiqueta 1", "Etiqueta 2", ...)` arma un caso de prueba (de Ecuador, salvo que
se pida otro país) con esas etiquetas y lo mapea contra el glosario, el maestro y las
reglas reales.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from registro_proveedor.config import RAIZ_PROYECTO
from registro_proveedor.dominio.casos import CampoSolicitado, CasoLeido, leer_caso
from registro_proveedor.dominio.lectura import ErrorDeDatos, cargar_glosario, cargar_maestro
from registro_proveedor.dominio.mapeo import (
    CampoMapeado,
    Decision,
    ErrorDeMapeo,
    Estado,
    Mapeo,
    Metodo,
    buscar_en_glosario,
    cargar_mapeo,
    confirmar_campo,
    guardar_mapeo,
    mapear_caso,
    valor_en_maestro,
)
from registro_proveedor.dominio.modelos import NOMBRES_PAIS, Formato, Maestro, Pais
from registro_proveedor.dominio.reglas import cargar_reglas
from tests.ayudas import DATOS_REALES, FECHA_FIJA, HORA_FIJA

GLOSARIO = cargar_glosario(DATOS_REALES)
MAESTRO = cargar_maestro(DATOS_REALES)
REGLAS = cargar_reglas(RAIZ_PROYECTO / "config" / "reglas.yaml")
CONTENIDO = MAESTRO.model_dump(mode="json")
CUENTA = "03100012345"
OTRA_HORA = datetime(2026, 9, 2, 8, 30, tzinfo=UTC)
CASOS = ["co-industrias-delta", "ec-corp-andina", "hn-agroexport-sula", "pa-logistica-istmo"]


def _caso(*etiquetas: str, pais: Pais = Pais.ECUADOR) -> CasoLeido:
    return CasoLeido(
        caso="caso-prueba",
        cliente="Cliente de prueba",
        pais=pais,
        pais_nombre=NOMBRES_PAIS[pais],
        formato=Formato.PDF,
        fecha=FECHA_FIJA,
        campos=[CampoSolicitado(etiqueta=e, obligatorio=True) for e in etiquetas],
        soportes=[],
        avisos=[],
    )


def _mapear(
    *etiquetas: str,
    pais: Pais = Pais.ECUADOR,
    anterior: Mapeo | None = None,
    maestro: Maestro = MAESTRO,
    glosario: dict[str, str] = GLOSARIO,
) -> Mapeo:
    return mapear_caso(
        _caso(*etiquetas, pais=pais),
        glosario,
        maestro,
        REGLAS,
        generado_en=HORA_FIJA,
        fecha_ejecucion=FECHA_FIJA,
        anterior=anterior,
    )


def _campo(etiqueta: str, pais: Pais = Pais.ECUADOR) -> CampoMapeado:
    return _mapear(etiqueta, pais=pais).campos[0]


def _mapear_real(caso: str) -> Mapeo:
    return mapear_caso(
        leer_caso(DATOS_REALES, caso), GLOSARIO, MAESTRO, REGLAS, HORA_FIJA, FECHA_FIJA
    )


# ---------- 1. Casos de referencia y la garantía principal ----------


@pytest.mark.parametrize(
    ("caso", "llenos", "faltantes", "por_confirmar"),
    [
        ("co-industrias-delta", 17, 0, 0),  # Colombia: el NIT queda lleno
        ("ec-corp-andina", 13, 1, 1),  # RUC por confirmar · falta "contribuyente especial"
        ("hn-agroexport-sula", 9, 1, 1),  # RTN por confirmar · falta "Referencias comerciales"
        ("pa-logistica-istmo", 8, 0, 1),  # RUC por confirmar
    ],
)
def test_casos_de_referencia(caso: str, llenos: int, faltantes: int, por_confirmar: int) -> None:
    m = _mapear_real(caso)
    assert len(m.en_estado(Estado.LLENO)) == llenos
    assert len(m.en_estado(Estado.FALTANTE)) == faltantes
    assert len(m.en_estado(Estado.REQUIERE_CONFIRMACION)) == por_confirmar
    assert m.version_maestro is None  # el maestro de ejemplo no tiene versión


# Etiquetas raras a propósito, para buscar valores "inventados".
ETIQUETAS_RARAS = [
    "Razon socail",
    "Num. de cuenta",
    "Nombre del representante legal",
    "Cuenta bancaria",
    "Correo",
    "x",
    "¿?",
    "SWIFT / BIC",
    "Número de contribuyente especial",
]


@pytest.mark.parametrize("caso", CASOS)
def test_ningun_valor_sale_de_fuera_del_maestro_en_los_casos(caso: str) -> None:
    _todo_valor_viene_del_maestro(_mapear_real(caso))


def test_ningun_valor_sale_de_fuera_del_maestro_con_etiquetas_raras() -> None:
    _todo_valor_viene_del_maestro(_mapear(*ETIQUETAS_RARAS))


def _todo_valor_viene_del_maestro(m: Mapeo) -> None:
    """Cada valor debe ser EXACTAMENTE lo que hay en el maestro en la ruta del campo."""
    for campo in m.campos:
        if campo.valor is not None:
            assert campo.ruta is not None
            assert campo.valor == valor_en_maestro(CONTENIDO, campo.ruta), campo.etiqueta


# ---------- 2. Las capas ----------


def test_capa_1_exacta() -> None:
    campo = _campo("Razón social")
    assert campo.estado is Estado.LLENO
    assert campo.metodo is Metodo.GLOSARIO_EXACTO
    assert campo.confianza == 1.0
    assert campo.ruta == "razon_social"
    assert campo.valor == "Empresa Ejemplo S.A.S."
    assert campo.nota == "igual a la etiqueta «Razón social» del glosario"


def test_capa_2_normalizada() -> None:
    campo = _campo("RAZON SOCIAL:")
    assert campo.estado is Estado.LLENO
    assert campo.metodo is Metodo.GLOSARIO_NORMALIZADO
    assert campo.confianza == REGLAS.mapeo.confianza_normalizado == 0.95
    assert campo.etiqueta_glosario == "Razón social"
    assert campo.valor == "Empresa Ejemplo S.A.S."


def test_capa_3_muy_parecida_se_llena() -> None:
    campo = _campo("Razon socail")  # error de escritura: 92 % parecida
    assert campo.estado is Estado.LLENO
    assert campo.metodo is Metodo.SIMILITUD
    assert campo.confianza >= 0.9
    assert "parecida a «Razón social» del glosario (92%)" in campo.nota


def test_capa_3_algo_parecida_pide_confirmacion() -> None:
    campo = _campo("Num. de cuenta")  # 90 % parecida a "Número de cuenta" → entre 0.8 y 0.9
    assert campo.estado is Estado.REQUIERE_CONFIRMACION
    assert 0.8 <= campo.confianza < 0.9
    assert campo.ruta == "banco.numero_cuenta"
    assert campo.valor == CUENTA  # aquí, en el dominio, el valor está completo
    assert "confirme que es el mismo dato" in campo.nota


def test_capa_3_poco_parecida_queda_faltante() -> None:
    campo = _campo("Cuenta bancaria")
    assert campo.estado is Estado.FALTANTE
    assert campo.metodo is Metodo.SIN_COINCIDENCIA
    assert campo.ruta is None and campo.valor is None
    assert campo.nota.startswith("la etiqueta no está en el glosario (lo más parecido fue")


def test_la_cedula_no_se_confunde_con_el_nombre() -> None:
    """Una medida de parecido más permisiva llenaría estos campos con el dato equivocado."""
    assert _campo("Cédula del representante legal").ruta == "representante_legal.identificacion"
    # "Nombre del representante legal" se parece a "Cargo del representante legal" (otro
    # dato): no se llena con él. Queda faltante para que la persona lo resuelva.
    nombre = _campo("Nombre del representante legal")
    assert nombre.estado is Estado.FALTANTE
    assert nombre.valor is None


def test_empate_entre_dos_datos_distintos_pide_confirmacion() -> None:
    # "Teléfono C" está a la misma distancia (una letra) de "Teléfono A" y de "Teléfono B",
    # que apuntan a datos DISTINTOS. No se puede elegir solo.
    glosario = {"Teléfono A": "telefono", "Teléfono B": "sitio_web"}
    coincidencia = buscar_en_glosario("Teléfono C", glosario, REGLAS.mapeo)
    assert coincidencia is not None
    assert coincidencia.confianza == 0.9  # suficiente para llenar... si no hubiera empate
    assert coincidencia.empate_con is not None
    campo = _mapear("Teléfono C", glosario=glosario).campos[0]
    assert campo.estado is Estado.REQUIERE_CONFIRMACION
    assert "pero también a" in campo.nota


def test_empate_entre_etiquetas_del_mismo_dato_no_es_problema() -> None:
    glosario = {"Teléfono A": "telefono", "Teléfono B": "telefono"}
    coincidencia = buscar_en_glosario("Teléfono C", glosario, REGLAS.mapeo)
    assert coincidencia is not None and coincidencia.empate_con is None


def test_glosario_vacio() -> None:
    assert buscar_en_glosario("Razón social", {}, REGLAS.mapeo) is None
    assert _mapear("Razón social", glosario={}).campos[0].estado is Estado.FALTANTE


def test_dato_que_el_maestro_no_tiene() -> None:
    sin_telefono = MAESTRO.model_copy(update={"telefono": None})
    campo = _mapear("Teléfono", maestro=sin_telefono).campos[0]
    assert campo.estado is Estado.FALTANTE
    assert campo.ruta == "telefono"  # se sabe dónde debería estar
    assert campo.valor is None
    assert campo.nota == "el maestro no tiene el dato «telefono»"


def test_se_copian_hoja_celda_y_obligatorio() -> None:
    banco = next(c for c in _mapear_real("co-industrias-delta").campos if c.etiqueta == "Banco")
    assert (banco.hoja, banco.celda, banco.obligatorio) == ("Datos Bancarios", "C3", None)


# ---------- 3. Regla de país RN1 ----------


@pytest.mark.parametrize(
    ("etiqueta", "pais", "nombre_id"),
    [
        ("RUC", Pais.ECUADOR, "RUC"),
        ("RUC", Pais.PANAMA, "RUC"),
        ("RUC", Pais.PERU, "RUC"),
        ("RTN", Pais.HONDURAS, "RTN"),
        # Lo que importa es el DATO (el NIT), no cómo se llame la etiqueta.
        ("Identificación tributaria", Pais.ECUADOR, "RUC"),
        ("NIT", Pais.HONDURAS, "RTN"),
    ],
)
def test_rn1_identificador_extranjero_pide_confirmacion(
    etiqueta: str, pais: Pais, nombre_id: str
) -> None:
    campo = _campo(etiqueta, pais=pais)
    assert campo.estado is Estado.REQUIERE_CONFIRMACION
    assert campo.valor == "900123456"  # se propone el NIT, que es lo que hay
    assert (
        f"identificador extranjero: el cliente de {NOMBRES_PAIS[pais]} pide {nombre_id}; "
        "la empresa solo tiene NIT de Colombia: confirme si se acepta"
    ) in campo.nota


def test_rn1_en_colombia_el_nit_queda_lleno() -> None:
    campo = _campo("NIT", pais=Pais.COLOMBIA)
    assert campo.estado is Estado.LLENO
    assert "identificador extranjero" not in campo.nota


def test_rn1_no_toca_otros_datos() -> None:
    assert _campo("Razón social", pais=Pais.HONDURAS).estado is Estado.LLENO


def test_rn1_confirmado_se_conserva_al_volver_a_mapear() -> None:
    m, _ = confirmar_campo(_mapear("RUC"), "RUC", Decision.ACEPTAR, "analista", OTRA_HORA)
    otra_vez = _mapear("RUC", anterior=m)
    assert otra_vez.campos[0].estado is Estado.LLENO
    assert otra_vez.campos[0].confirmacion is not None


# ---------- 4. Cómo se convierte cada valor del maestro en texto ----------


@pytest.mark.parametrize(
    ("ruta", "esperado"),
    [
        ("razon_social", "Empresa Ejemplo S.A.S."),
        ("numero_empleados", "480"),  # número entero
        ("ingresos_ultimo_ano.valor", "98000000000"),  # dinero (Decimal), sin notación rara
        ("fecha_constitucion", "2008-03-14"),  # fecha en formato AAAA-MM-DD
        ("gran_contribuyente", "No"),  # verdadero/falso → Sí/No
        ("pais", "CO"),
        ("banco", None),  # un grupo entero no es un valor
        ("certificaciones", None),  # una lista tampoco
        ("no_existe", None),
        ("banco.no_existe", None),
        ("nit.numero", None),  # no se puede entrar en un valor
    ],
)
def test_valor_en_maestro(ruta: str, esperado: str | None) -> None:
    assert valor_en_maestro(CONTENIDO, ruta) == esperado


# ---------- 5. Confirmación ----------


def _con_pendiente() -> Mapeo:
    """Un mapeo con un campo por confirmar ("Num. de cuenta") y otros dos ya resueltos."""
    m = _mapear("Razón social", "Num. de cuenta", "Cuenta bancaria")
    assert [c.estado for c in m.campos] == [
        Estado.LLENO,
        Estado.REQUIERE_CONFIRMACION,
        Estado.FALTANTE,
    ]
    return m


def test_aceptar_llena_el_campo_y_no_toca_los_demas() -> None:
    m = _con_pendiente()
    nuevo, campo = confirmar_campo(m, "Num. de cuenta", Decision.ACEPTAR, "analista", OTRA_HORA)
    assert campo.estado is Estado.LLENO
    assert campo.valor == CUENTA
    assert campo.confirmacion is not None
    assert campo.confirmacion.por == "analista"
    assert campo.confirmacion.en == OTRA_HORA
    assert campo.nota == m.campos[1].nota  # la nota sigue explicando por qué se preguntó
    assert nuevo.campos[1] == campo
    assert [nuevo.campos[0], nuevo.campos[2]] == [m.campos[0], m.campos[2]]  # intactos


def test_dejar_faltante_vacia_el_campo_y_guarda_lo_propuesto() -> None:
    _, campo = confirmar_campo(
        _con_pendiente(), "Num. de cuenta", Decision.DEJAR_FALTANTE, "analista", OTRA_HORA
    )
    assert campo.estado is Estado.FALTANTE
    assert campo.valor is None
    assert campo.confirmacion is not None
    assert campo.confirmacion.valor_propuesto == CUENTA  # para poder cambiar de opinión


def test_cambiar_de_opinion() -> None:
    original = _con_pendiente()
    m, _ = confirmar_campo(
        original, "Num. de cuenta", Decision.DEJAR_FALTANTE, "analista", OTRA_HORA
    )
    _, campo = confirmar_campo(m, "Num. de cuenta", Decision.ACEPTAR, "analista", OTRA_HORA)
    assert campo.estado is Estado.LLENO
    assert campo.valor == CUENTA  # se recuperó el valor propuesto
    assert campo.confirmacion is not None and campo.confirmacion.decision is Decision.ACEPTAR
    assert campo.nota == original.campos[1].nota


def test_la_etiqueta_se_encuentra_sin_mayusculas_ni_tildes() -> None:
    _, campo = confirmar_campo(
        _con_pendiente(), "num de cuenta", Decision.ACEPTAR, "analista", OTRA_HORA
    )
    assert campo.etiqueta == "Num. de cuenta"


def test_no_se_confirma_un_campo_lleno() -> None:
    with pytest.raises(ErrorDeMapeo, match=r"está «lleno».*Pendientes: «Num\. de cuenta»"):
        confirmar_campo(_con_pendiente(), "Razón social", Decision.ACEPTAR, "analista", OTRA_HORA)


def test_etiqueta_inexistente() -> None:
    with pytest.raises(ErrorDeMapeo, match="no hay un campo «NIT»"):
        confirmar_campo(_con_pendiente(), "NIT", Decision.ACEPTAR, "analista", OTRA_HORA)


def test_volver_a_mapear_conserva_la_decision() -> None:
    m, _ = confirmar_campo(
        _con_pendiente(), "Num. de cuenta", Decision.ACEPTAR, "analista", OTRA_HORA
    )
    otra_vez = _mapear("Razón social", "Num. de cuenta", "Cuenta bancaria", anterior=m)
    assert otra_vez.campos[1].estado is Estado.LLENO
    assert otra_vez.campos[1].confirmacion == m.campos[1].confirmacion


def test_si_el_maestro_cambio_hay_que_volver_a_confirmar() -> None:
    m, _ = confirmar_campo(
        _con_pendiente(), "Num. de cuenta", Decision.ACEPTAR, "analista", OTRA_HORA
    )
    assert MAESTRO.banco is not None
    otra_cuenta = MAESTRO.model_copy(
        update={"banco": MAESTRO.banco.model_copy(update={"numero_cuenta": "99999999999"})}
    )
    otra_vez = _mapear(
        "Razón social", "Num. de cuenta", "Cuenta bancaria", anterior=m, maestro=otra_cuenta
    )
    assert otra_vez.campos[1].estado is Estado.REQUIERE_CONFIRMACION
    assert otra_vez.campos[1].confirmacion is None


# ---------- La garantía, revisada por el propio modelo ----------


def _base(**cambios: object) -> dict[str, object]:
    datos: dict[str, object] = {
        "etiqueta": "X",
        "obligatorio": None,
        "hoja": None,
        "celda_etiqueta": None,
        "celda": None,
        "estado": "lleno",
        "metodo": "glosario_exacto",
        "confianza": 1.0,
        "etiqueta_glosario": "X",
        "ruta": "nit",
        "valor": "900123456",
        "nota": "n",
    }
    return {**datos, **cambios}


@pytest.mark.parametrize(
    ("cambios", "mensaje"),
    [
        ({"ruta": None}, "valor inventado"),
        ({"estado": "faltante"}, "un campo faltante no puede tener valor"),
        ({"valor": None}, "necesita un valor"),
    ],
)
def test_un_campo_incoherente_no_se_puede_crear(cambios: dict[str, object], mensaje: str) -> None:
    with pytest.raises(ValidationError, match=mensaje):
        CampoMapeado.model_validate(_base(**cambios))


# ---------- 6. mapeo.json ----------


def test_guardar_y_leer(tmp_path: Path) -> None:
    m, _ = confirmar_campo(
        _con_pendiente(), "Num. de cuenta", Decision.ACEPTAR, "analista", OTRA_HORA
    )
    ruta = guardar_mapeo(tmp_path, m)
    assert ruta.name == "mapeo.json"
    assert CUENTA in ruta.read_text(encoding="utf-8")  # el archivo tiene el valor completo
    assert cargar_mapeo(tmp_path) == m
    assert [p.name for p in tmp_path.iterdir()] == ["mapeo.json"]  # no queda el temporal


def test_leer_sin_mapeo(tmp_path: Path) -> None:
    assert cargar_mapeo(tmp_path) is None


def test_leer_mapeo_danado(tmp_path: Path) -> None:
    (tmp_path / "mapeo.json").write_text('{"caso": "x"}', encoding="utf-8")
    with pytest.raises(ErrorDeDatos, match="falta este campo obligatorio"):
        cargar_mapeo(tmp_path)


def test_fecha_y_hora_del_mapeo() -> None:
    m = _mapear("Razón social")
    assert m.generado_en == HORA_FIJA
    assert m.fecha_ejecucion == date(2026, 9, 1)
