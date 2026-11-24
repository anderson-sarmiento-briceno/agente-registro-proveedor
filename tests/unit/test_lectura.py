"""Pruebas de la lectura de insumos: modelos y mensajes de error en español."""

from pathlib import Path

import pytest

from registro_proveedor.dominio.lectura import (
    ErrorDeDatos,
    cargar_glosario,
    cargar_indice_soportes,
    cargar_maestro,
    cargar_plantilla_campos,
    cargar_plantilla_celdas,
    cargar_solicitud,
    cargar_soportes_exigidos,
    carpeta_de_caso,
    leer_json,
)
from registro_proveedor.dominio.modelos import Formato, Pais, TipoSoporte
from tests.ayudas import DATOS_REALES, EditarJson, como_dict, como_lista

CASOS = ["co-industrias-delta", "ec-corp-andina", "hn-agroexport-sula", "pa-logistica-istmo"]


# ---------- Los datos reales se leen bien ----------


@pytest.mark.parametrize("caso", CASOS)
def test_solicitudes_reales_se_leen(caso: str) -> None:
    solicitud = cargar_solicitud(carpeta_de_caso(DATOS_REALES, caso))
    assert solicitud.id == caso


def test_valores_de_los_casos_reales() -> None:
    co = cargar_solicitud(carpeta_de_caso(DATOS_REALES, "co-industrias-delta"))
    assert co.pais is Pais.COLOMBIA
    assert co.formato is Formato.EXCEL
    celdas = cargar_plantilla_celdas(carpeta_de_caso(DATOS_REALES, "co-industrias-delta"))
    assert {c.hoja for c in celdas} == {"Datos Proveedor", "Datos Bancarios"}
    campos = cargar_plantilla_campos(carpeta_de_caso(DATOS_REALES, "ec-corp-andina"))
    assert campos[0].etiqueta == "Nombre de la empresa"
    exigidos = cargar_soportes_exigidos(carpeta_de_caso(DATOS_REALES, "ec-corp-andina"))
    assert TipoSoporte.CERTIFICADO_CUMPLIMIENTO_TRIBUTARIO in exigidos


def test_repositorio_real_se_lee() -> None:
    maestro = cargar_maestro(DATOS_REALES)
    assert maestro.razon_social == "Empresa Ejemplo S.A.S."
    assert maestro.banco is not None
    assert maestro.version is None  # los datos de ejemplo no la tienen
    assert len(cargar_indice_soportes(DATOS_REALES)) == 6
    assert cargar_glosario(DATOS_REALES)["SWIFT"] == "banco.swift"


# ---------- Casos inexistentes o con nombres peligrosos ----------


def test_caso_inexistente() -> None:
    with pytest.raises(ErrorDeDatos, match="no existe el caso «no-existe»"):
        carpeta_de_caso(DATOS_REALES, "no-existe")


@pytest.mark.parametrize("nombre", ["../repositorio", "CO-Mayus", "con espacio", ""])
def test_nombre_de_caso_invalido(nombre: str) -> None:
    with pytest.raises(ErrorDeDatos, match="no es válido"):
        carpeta_de_caso(DATOS_REALES, nombre)


# ---------- Mensajes de error claros ----------


def _problemas(error: pytest.ExceptionInfo[ErrorDeDatos]) -> str:
    return " | ".join(error.value.problemas)


def test_formato_desconocido(datos: Path, editar_json: EditarJson) -> None:
    caso = "co-industrias-delta"
    editar_json(f"casos/{caso}/solicitud.json", lambda s: {**como_dict(s), "formato": "excel"})
    with pytest.raises(ErrorDeDatos) as error:
        cargar_solicitud(datos / "casos" / caso)
    assert "«formato»: el valor «excel» no es válido" in _problemas(error)
    assert "'xlsx'" in _problemas(error)


def test_fecha_invalida(datos: Path, editar_json: EditarJson) -> None:
    caso = "co-industrias-delta"
    editar_json(f"casos/{caso}/solicitud.json", lambda s: {**como_dict(s), "fecha": "25/08/2026"})
    with pytest.raises(ErrorDeDatos) as error:
        cargar_solicitud(datos / "casos" / caso)
    assert "no es una fecha válida (formato AAAA-MM-DD)" in _problemas(error)


def test_campo_obligatorio_y_campo_desconocido(datos: Path, editar_json: EditarJson) -> None:
    caso = "co-industrias-delta"

    def romper(s: object) -> object:
        d = como_dict(s)
        del d["cliente"]
        d["clente"] = "mal escrito"
        return d

    editar_json(f"casos/{caso}/solicitud.json", romper)
    with pytest.raises(ErrorDeDatos) as error:
        cargar_solicitud(datos / "casos" / caso)
    assert "«cliente»: falta este campo obligatorio" in _problemas(error)
    assert "«clente»: campo no reconocido" in _problemas(error)


def test_celda_invalida_indica_el_elemento(datos: Path, editar_json: EditarJson) -> None:
    caso = "co-industrias-delta"

    def romper(celdas: object) -> object:
        lista = como_lista(celdas)
        lista[2] = {**como_dict(lista[2]), "celda_valor": "C0"}
        return lista

    editar_json(f"casos/{caso}/plantilla-celdas.json", romper)
    with pytest.raises(ErrorDeDatos) as error:
        cargar_plantilla_celdas(datos / "casos" / caso)
    assert "elemento 3 > «celda_valor»: el valor «C0» no es válido" in _problemas(error)
    assert "como «B3»" in _problemas(error)


def test_plantilla_vacia(datos: Path, editar_json: EditarJson) -> None:
    editar_json("casos/ec-corp-andina/plantilla-campos.json", lambda _: [])
    with pytest.raises(ErrorDeDatos, match="la lista no puede estar vacía"):
        cargar_plantilla_campos(datos / "casos" / "ec-corp-andina")


def test_tipo_de_soporte_desconocido(datos: Path, editar_json: EditarJson) -> None:
    editar_json("casos/ec-corp-andina/soportes-exigidos.json", lambda _: ["rut", "pasaporte"])
    with pytest.raises(ErrorDeDatos) as error:
        cargar_soportes_exigidos(datos / "casos" / "ec-corp-andina")
    assert "elemento 2: el valor «pasaporte» no es válido" in _problemas(error)


def test_maestro_con_tipo_incorrecto(datos: Path, editar_json: EditarJson) -> None:
    editar_json("repositorio/maestro.json", lambda m: {**como_dict(m), "nit": 900123456})
    with pytest.raises(ErrorDeDatos, match="«nit»: debe ser texto"):
        cargar_maestro(datos)


def test_maestro_sin_razon_social(datos: Path, editar_json: EditarJson) -> None:
    editar_json(
        "repositorio/maestro.json",
        lambda m: {k: v for k, v in como_dict(m).items() if k != "razon_social"},
    )
    with pytest.raises(ErrorDeDatos, match="«razon_social»: falta este campo obligatorio"):
        cargar_maestro(datos)


def test_maestro_acepta_campos_nuevos(datos: Path, editar_json: EditarJson) -> None:
    editar_json("repositorio/maestro.json", lambda m: {**como_dict(m), "campo_nuevo": "x"})
    maestro = cargar_maestro(datos)
    assert maestro.model_extra == {"campo_nuevo": "x"}


def test_soporte_con_ruta_peligrosa(datos: Path, editar_json: EditarJson) -> None:
    def romper(indice: object) -> object:
        lista = como_lista(indice)
        lista[0] = {**como_dict(lista[0]), "archivo": "../../maestro.json"}
        return lista

    editar_json("repositorio/soportes/index.json", romper)
    with pytest.raises(ErrorDeDatos, match="sin carpetas"):
        cargar_indice_soportes(datos)


def test_ruta_de_glosario_mal_escrita(datos: Path, editar_json: EditarJson) -> None:
    editar_json("glosario-campos.json", lambda g: {**como_dict(g), "SWIFT": "Banco.SWIFT"})
    with pytest.raises(ErrorDeDatos, match=r"como «banco\.swift»"):
        cargar_glosario(datos)


# ---------- Problemas del archivo JSON en sí ----------


def test_archivo_inexistente(tmp_path: Path) -> None:
    with pytest.raises(ErrorDeDatos, match="no existe el archivo"):
        leer_json(tmp_path / "nada.json")


def test_json_mal_formado(tmp_path: Path) -> None:
    ruta = tmp_path / "roto.json"
    ruta.write_text('{"a": 1,\n "b": }', encoding="utf-8")
    with pytest.raises(ErrorDeDatos, match=r"no es un JSON válido \(línea 2"):
        leer_json(ruta)


def test_json_con_clave_repetida(tmp_path: Path) -> None:
    ruta = tmp_path / "repetida.json"
    ruta.write_text('{"NIT": "nit", "NIT": "otra"}', encoding="utf-8")
    with pytest.raises(ErrorDeDatos, match="la clave «NIT» está repetida"):
        leer_json(ruta)


def test_json_que_no_es_utf8(tmp_path: Path) -> None:
    ruta = tmp_path / "latin1.json"
    ruta.write_bytes('{"a": "Razón"}'.encode("latin-1"))
    with pytest.raises(ErrorDeDatos, match="no está en UTF-8"):
        leer_json(ruta)
