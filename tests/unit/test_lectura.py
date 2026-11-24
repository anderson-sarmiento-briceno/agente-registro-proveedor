"""Pruebas de `dominio/lectura.py`: que los datos se lean bien y que los errores se entiendan.

Cómo está organizado:
    1. Los datos reales se leen sin errores y con los valores esperados.
    2. Los nombres de caso inválidos o peligrosos se rechazan.
    3. Cada tipo de error de contenido produce un mensaje claro en español.
    4. Los problemas del archivo en sí (no existe, JSON roto, clave repetida...) se detectan.

Cómo se lee una prueba:
    - `pytest.raises(ErrorDeDatos)` verifica que el código lance ese error. Con
      `match="..."` además exige que el mensaje contenga ese texto (es una
      expresión regular: por eso los "." y los "(" se escriben con `\\` y en `r"..."`).
    - `@pytest.mark.parametrize` repite la misma prueba con varios valores: cada
      valor cuenta como una prueba distinta en el resultado.
"""

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


def _problemas(error: pytest.ExceptionInfo[ErrorDeDatos]) -> str:
    """Todos los problemas de un `ErrorDeDatos` en un solo texto, para buscar dentro."""
    return " | ".join(error.value.problemas)


# ---------- 1. Los datos reales se leen bien ----------


@pytest.mark.parametrize("caso", CASOS)
def test_solicitudes_reales_se_leen(caso: str) -> None:
    solicitud = cargar_solicitud(carpeta_de_caso(DATOS_REALES, caso))
    assert solicitud.id == caso


def test_valores_de_los_casos_reales() -> None:
    # Pydantic convierte los textos del JSON en los tipos del modelo: "CO" → Pais.COLOMBIA.
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


# ---------- 2. Casos inexistentes o con nombres peligrosos ----------


def test_caso_inexistente() -> None:
    with pytest.raises(ErrorDeDatos, match="no existe el caso «no-existe»"):
        carpeta_de_caso(DATOS_REALES, "no-existe")


# "../repositorio" intenta salir de datos/casos/ (path traversal). Los demás no
# cumplen el patrón: mayúsculas, espacios o vacío.
@pytest.mark.parametrize("nombre", ["../repositorio", "CO-Mayus", "con espacio", ""])
def test_nombre_de_caso_invalido(nombre: str) -> None:
    with pytest.raises(ErrorDeDatos, match="no es válido"):
        carpeta_de_caso(DATOS_REALES, nombre)


# ---------- 3. Mensajes de error claros ----------


def test_formato_desconocido(datos: Path, editar_json: EditarJson) -> None:
    caso = "co-industrias-delta"
    editar_json(f"casos/{caso}/solicitud.json", lambda s: {**como_dict(s), "formato": "excel"})
    with pytest.raises(ErrorDeDatos) as error:
        cargar_solicitud(datos / "casos" / caso)
    # El mensaje dice qué valor llegó y cuáles se esperaban.
    assert "«formato»: el valor «excel» no es válido" in _problemas(error)
    assert "'xlsx'" in _problemas(error)


def test_fecha_invalida(datos: Path, editar_json: EditarJson) -> None:
    caso = "co-industrias-delta"
    editar_json(f"casos/{caso}/solicitud.json", lambda s: {**como_dict(s), "fecha": "25/08/2026"})
    with pytest.raises(ErrorDeDatos) as error:
        cargar_solicitud(datos / "casos" / caso)
    assert "no es una fecha válida (formato AAAA-MM-DD)" in _problemas(error)


def test_varios_problemas_se_reportan_juntos(datos: Path, editar_json: EditarJson) -> None:
    """Un campo que falta y otro mal escrito: los dos aparecen en el mismo error."""
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
        lista[2] = {**como_dict(lista[2]), "celda_valor": "C0"}  # posición 2 = elemento 3
        return lista

    editar_json(f"casos/{caso}/plantilla-celdas.json", romper)
    with pytest.raises(ErrorDeDatos) as error:
        cargar_plantilla_celdas(datos / "casos" / caso)
    assert "elemento 3 > «celda_valor»: el valor «C0» no es válido" in _problemas(error)
    assert "como «B3»" in _problemas(error)  # la pista en español, no la expresión regular


@pytest.mark.parametrize(
    ("hoja", "esperado"),
    [
        ("Una hoja con un nombre demasiado largo", "es demasiado largo (máximo 31 caracteres)"),
        ("Datos: Proveedor", "un nombre de hoja sin los caracteres"),
    ],
)
def test_nombre_de_hoja_invalido(
    datos: Path, editar_json: EditarJson, hoja: str, esperado: str
) -> None:
    caso = "co-industrias-delta"

    def romper(celdas: object) -> object:
        lista = como_lista(celdas)
        lista[0] = {**como_dict(lista[0]), "hoja": hoja}
        return lista

    editar_json(f"casos/{caso}/plantilla-celdas.json", romper)
    with pytest.raises(ErrorDeDatos) as error:
        cargar_plantilla_celdas(datos / "casos" / caso)
    assert esperado in _problemas(error)


def test_obligatorio_que_no_es_booleano(datos: Path, editar_json: EditarJson) -> None:
    def romper(campos: object) -> object:
        lista = como_lista(campos)
        lista[0] = {**como_dict(lista[0]), "obligatorio": "si"}
        return lista

    editar_json("casos/ec-corp-andina/plantilla-campos.json", romper)
    with pytest.raises(ErrorDeDatos, match="«obligatorio»: debe ser true o false"):
        cargar_plantilla_campos(datos / "casos" / "ec-corp-andina")


def test_texto_con_solo_espacios_cuenta_como_vacio(datos: Path, editar_json: EditarJson) -> None:
    caso = "co-industrias-delta"
    editar_json(f"casos/{caso}/solicitud.json", lambda s: {**como_dict(s), "cliente": "   "})
    with pytest.raises(ErrorDeDatos, match="«cliente»: no puede estar vacío"):
        cargar_solicitud(datos / "casos" / caso)


def test_adjuntos_que_no_son_lista(datos: Path, editar_json: EditarJson) -> None:
    caso = "co-industrias-delta"
    editar_json(f"casos/{caso}/solicitud.json", lambda s: {**como_dict(s), "adjuntos": "a.xlsx"})
    with pytest.raises(ErrorDeDatos, match="«adjuntos»: debe ser una lista"):
        cargar_solicitud(datos / "casos" / caso)


def test_plantilla_vacia(datos: Path, editar_json: EditarJson) -> None:
    editar_json("casos/ec-corp-andina/plantilla-campos.json", lambda _: [])
    with pytest.raises(ErrorDeDatos, match="la lista no puede estar vacía"):
        cargar_plantilla_campos(datos / "casos" / "ec-corp-andina")


def test_tipo_de_soporte_desconocido(datos: Path, editar_json: EditarJson) -> None:
    editar_json("casos/ec-corp-andina/soportes-exigidos.json", lambda _: ["rut", "pasaporte"])
    with pytest.raises(ErrorDeDatos) as error:
        cargar_soportes_exigidos(datos / "casos" / "ec-corp-andina")
    assert "elemento 2: el valor «pasaporte» no es válido" in _problemas(error)


# Errores de tipo en el maestro. Para cada campo, un valor del tipo equivocado y el
# mensaje esperado. (Ojo: Pydantic convierte "480" en 480 sin quejarse, por eso
# se usa un texto que no es un número.)
@pytest.mark.parametrize(
    ("campo", "valor", "esperado"),
    [
        ("nit", 900123456, "«nit»: debe ser texto"),
        ("numero_empleados", "muchos", "«numero_empleados»: debe ser un número entero"),
        ("fecha_constitucion", "ayer", "«fecha_constitucion»: «ayer» no es una fecha válida"),
        ("banco", "Bancolombia", "«banco»: debe ser un objeto"),
    ],
)
def test_maestro_con_tipo_incorrecto(
    datos: Path, editar_json: EditarJson, campo: str, valor: object, esperado: str
) -> None:
    editar_json("repositorio/maestro.json", lambda m: {**como_dict(m), campo: valor})
    with pytest.raises(ErrorDeDatos) as error:
        cargar_maestro(datos)
    assert esperado in _problemas(error)


def test_ingresos_con_valor_que_no_es_numero(datos: Path, editar_json: EditarJson) -> None:
    def romper(m: object) -> object:
        d = como_dict(m)
        d["ingresos_ultimo_ano"] = {**como_dict(d["ingresos_ultimo_ano"]), "valor": "mucho"}
        return d

    editar_json("repositorio/maestro.json", romper)
    with pytest.raises(ErrorDeDatos) as error:
        cargar_maestro(datos)
    # La ubicación muestra el camino completo dentro del JSON.
    assert "«ingresos_ultimo_ano» > «valor»: debe ser un número" in _problemas(error)


def test_maestro_sin_razon_social(datos: Path, editar_json: EditarJson) -> None:
    editar_json(
        "repositorio/maestro.json",
        lambda m: {k: v for k, v in como_dict(m).items() if k != "razon_social"},
    )
    with pytest.raises(ErrorDeDatos, match="«razon_social»: falta este campo obligatorio"):
        cargar_maestro(datos)


def test_maestro_acepta_campos_nuevos(datos: Path, editar_json: EditarJson) -> None:
    """El maestro es tolerante: un campo nuevo no rompe la lectura, queda en `model_extra`."""
    editar_json("repositorio/maestro.json", lambda m: {**como_dict(m), "campo_nuevo": "x"})
    maestro = cargar_maestro(datos)
    assert maestro.model_extra == {"campo_nuevo": "x"}


def test_soporte_con_ruta_peligrosa(datos: Path, editar_json: EditarJson) -> None:
    """Un soporte no puede apuntar fuera de su carpeta (path traversal)."""

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


# ---------- 4. Problemas del archivo JSON en sí ----------


def test_archivo_inexistente(tmp_path: Path) -> None:
    with pytest.raises(ErrorDeDatos, match="no existe el archivo"):
        leer_json(tmp_path / "nada.json")


def test_json_mal_formado(tmp_path: Path) -> None:
    ruta = tmp_path / "roto.json"
    ruta.write_text('{"a": 1,\n "b": }', encoding="utf-8")  # falta el valor de "b"
    with pytest.raises(ErrorDeDatos, match=r"no es un JSON válido \(línea 2"):
        leer_json(ruta)


def test_json_con_clave_repetida(tmp_path: Path) -> None:
    ruta = tmp_path / "repetida.json"
    ruta.write_text('{"NIT": "nit", "NIT": "otra"}', encoding="utf-8")
    with pytest.raises(ErrorDeDatos, match="la clave «NIT» está repetida"):
        leer_json(ruta)


def test_json_que_no_es_utf8(tmp_path: Path) -> None:
    ruta = tmp_path / "latin1.json"
    ruta.write_bytes('{"a": "Razón"}'.encode("latin-1"))  # la "ó" en latin-1 no es UTF-8
    with pytest.raises(ErrorDeDatos, match="no está en UTF-8"):
        leer_json(ruta)


def test_json_con_bom_se_acepta(tmp_path: Path) -> None:
    """Algunos editores de Windows guardan UTF-8 con una marca invisible (BOM) al inicio."""
    ruta = tmp_path / "con-bom.json"
    ruta.write_bytes('{"a": "Razón"}'.encode("utf-8-sig"))
    assert leer_json(ruta) == {"a": "Razón"}
