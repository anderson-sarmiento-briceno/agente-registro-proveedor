"""Pruebas de `dominio/casos.py`: listar y leer los casos.

Las pruebas de lectura comprueban los 4 casos de referencia uno por uno, con los
valores que tienen los datos reales. Las de errores usan una copia rota (`datos`).
"""

from pathlib import Path

import pytest

from registro_proveedor.dominio.casos import (
    AVISO_PORTAL,
    AVISO_PORTAL_SIN_CAMPOS,
    CampoSolicitado,
    leer_caso,
    listar_casos,
)
from registro_proveedor.dominio.lectura import ErrorDeCaso, ErrorDeDatos
from registro_proveedor.dominio.modelos import Formato, Pais, TipoSoporte
from tests.ayudas import DATOS_REALES, EditarJson, como_dict, como_lista

TODOS = ["co-industrias-delta", "ec-corp-andina", "hn-agroexport-sula", "pa-logistica-istmo"]


# ---------- Listado ----------


def test_lista_todos_los_casos_en_orden() -> None:
    listado = listar_casos(DATOS_REALES)
    assert [c.caso for c in listado.casos] == TODOS
    assert listado.casos_con_error == []


def test_datos_de_un_caso_en_el_listado() -> None:
    ec = listar_casos(DATOS_REALES, "Ecuador").casos[0]
    assert ec.cliente == "Corporación Andina de Servicios S.A."
    assert ec.pais is Pais.ECUADOR
    assert ec.pais_nombre == "Ecuador"
    assert ec.formato is Formato.PDF
    assert str(ec.fecha) == "2026-08-27"


@pytest.mark.parametrize(
    ("filtro", "esperados"),
    [
        ("Ecuador", ["ec-corp-andina"]),  # nombre del país
        ("ecuador", ["ec-corp-andina"]),  # sin importar mayúsculas
        ("EC", ["ec-corp-andina"]),  # código del país
        ("andina", ["ec-corp-andina"]),  # palabra del cliente
        ("Panamá", ["pa-logistica-istmo"]),
        ("panama", ["pa-logistica-istmo"]),  # sin tilde
        ("indus", ["co-industrias-delta"]),  # comienzo de una palabra (4 letras o más)
        ("CO", ["co-industrias-delta"]),  # "co" NO encuentra "corp" (palabra corta)
        ("logistica istmo", ["pa-logistica-istmo"]),  # varias palabras: todas deben estar
        # Ambiguo: devuelve varios (también "S.A.S." contiene "S" y "A").
        ("S.A.", ["co-industrias-delta", "ec-corp-andina", "pa-logistica-istmo"]),
        ("Perú", []),  # no hay casos de Perú
        ("", TODOS),  # filtro vacío = sin filtro
    ],
)
def test_filtro(filtro: str, esperados: list[str]) -> None:
    assert [c.caso for c in listar_casos(DATOS_REALES, filtro).casos] == esperados


def test_un_caso_roto_no_detiene_el_listado(datos: Path) -> None:
    (datos / "casos/hn-agroexport-sula/solicitud.json").write_text("{roto", encoding="utf-8")
    listado = listar_casos(datos)
    assert [c.caso for c in listado.casos] == [
        "co-industrias-delta",
        "ec-corp-andina",
        "pa-logistica-istmo",
    ]
    assert len(listado.casos_con_error) == 1
    roto = listado.casos_con_error[0]
    assert roto.caso == "hn-agroexport-sula"
    assert roto.error.startswith("solicitud.json: no es un JSON válido")


def test_el_caso_roto_tambien_se_filtra(datos: Path) -> None:
    (datos / "casos/hn-agroexport-sula/solicitud.json").write_text("{roto", encoding="utf-8")
    assert listar_casos(datos, "Ecuador").casos_con_error == []
    assert len(listar_casos(datos, "agroexport").casos_con_error) == 1


def test_caso_con_id_distinto_a_la_carpeta(datos: Path, editar_json: EditarJson) -> None:
    editar_json("casos/ec-corp-andina/solicitud.json", lambda s: {**como_dict(s), "id": "otro"})
    listado = listar_casos(datos)
    assert "el id «otro» no coincide" in listado.casos_con_error[0].error


def test_sin_carpeta_de_casos(tmp_path: Path) -> None:
    with pytest.raises(ErrorDeDatos, match="no existe la carpeta de casos"):
        listar_casos(tmp_path)


# ---------- Lectura: los 4 casos de referencia ----------


@pytest.mark.parametrize(
    ("caso", "pais", "formato", "n_campos", "soportes"),
    [
        (
            "co-industrias-delta",
            Pais.COLOMBIA,
            Formato.EXCEL,
            17,
            ["camara_comercio", "rut", "certificacion_bancaria", "estados_financieros"],
        ),
        (
            "ec-corp-andina",
            Pais.ECUADOR,
            Formato.PDF,
            15,
            [
                "camara_comercio",
                "rut",
                "certificacion_bancaria",
                "estados_financieros",
                "certificado_cumplimiento_tributario",
            ],
        ),
        (
            "hn-agroexport-sula",
            Pais.HONDURAS,
            Formato.EXCEL,
            11,
            ["camara_comercio", "rut", "parafiscales"],
        ),
        ("pa-logistica-istmo", Pais.PANAMA, Formato.PORTAL, 9, ["camara_comercio", "rut"]),
    ],
)
def test_lectura_de_los_casos_de_referencia(
    caso: str, pais: Pais, formato: Formato, n_campos: int, soportes: list[str]
) -> None:
    leido = leer_caso(DATOS_REALES, caso)
    assert leido.caso == caso
    assert leido.pais is pais
    assert leido.formato is formato
    assert len(leido.campos) == n_campos
    assert leido.soportes == [TipoSoporte(s) for s in soportes]


def test_campos_de_excel_traen_hoja_y_celda() -> None:
    campos = leer_caso(DATOS_REALES, "co-industrias-delta").campos
    assert campos[0] == CampoSolicitado(
        etiqueta="Razón social",
        obligatorio=None,
        hoja="Datos Proveedor",
        celda_etiqueta="B3",
        celda="C3",
    )
    # El banco va en la segunda hoja.
    assert campos[-1] == CampoSolicitado(
        etiqueta="Titular de la cuenta",
        obligatorio=None,
        hoja="Datos Bancarios",
        celda_etiqueta="B6",
        celda="C6",
    )


def test_campos_de_pdf_traen_obligatorio_y_respetan_el_orden() -> None:
    campos = leer_caso(DATOS_REALES, "ec-corp-andina").campos
    assert campos[0] == CampoSolicitado(etiqueta="Nombre de la empresa", obligatorio=True)
    assert campos[2] == CampoSolicitado(
        etiqueta="Número de contribuyente especial", obligatorio=False
    )
    assert all(c.hoja is None and c.celda is None for c in campos)


def test_excel_y_pdf_no_tienen_avisos() -> None:
    assert leer_caso(DATOS_REALES, "co-industrias-delta").avisos == []
    assert leer_caso(DATOS_REALES, "ec-corp-andina").avisos == []


def test_portal_avisa_que_no_genera_formulario() -> None:
    assert leer_caso(DATOS_REALES, "pa-logistica-istmo").avisos == [AVISO_PORTAL]


def test_portal_sin_plantilla_avisa_que_no_hay_campos(datos: Path) -> None:
    (datos / "casos/pa-logistica-istmo/plantilla-campos.json").unlink()
    leido = leer_caso(datos, "pa-logistica-istmo")
    assert leido.campos == []
    assert leido.avisos == [AVISO_PORTAL, AVISO_PORTAL_SIN_CAMPOS]


def test_no_devuelve_el_cuerpo_del_correo() -> None:
    """Principio 5: el correo es contenido externo; no se le pasa al modelo."""
    leido = leer_caso(DATOS_REALES, "ec-corp-andina")
    assert "cuerpo" not in leido.model_dump()
    assert "Adjuntamos el formulario" not in leido.model_dump_json()


# ---------- Lectura: errores ----------


def test_caso_inexistente() -> None:
    with pytest.raises(ErrorDeCaso, match="no existe el caso «no-existe»"):
        leer_caso(DATOS_REALES, "no-existe")


def test_plantilla_corrupta(datos: Path, editar_json: EditarJson) -> None:
    def romper(celdas: object) -> object:
        lista = como_lista(celdas)
        lista[0] = {**como_dict(lista[0]), "celda_valor": "C0"}
        return lista

    editar_json("casos/co-industrias-delta/plantilla-celdas.json", romper)
    with pytest.raises(ErrorDeDatos, match="elemento 1 > «celda_valor»"):
        leer_caso(datos, "co-industrias-delta")


def test_pdf_sin_plantilla(datos: Path) -> None:
    (datos / "casos/ec-corp-andina/plantilla-campos.json").unlink()
    with pytest.raises(ErrorDeDatos, match="no existe el archivo"):
        leer_caso(datos, "ec-corp-andina")
