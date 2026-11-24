"""Pruebas de las herramientas proveedor_mapear_campos y proveedor_confirmar_campo.

La lógica del mapeo ya se prueba en test_mapeo.py. Aquí se prueba lo propio de las
herramientas:
    - que guarden out/<caso>/mapeo.json con los valores COMPLETOS,
    - que lo que ve el modelo tenga lo sensible ENMASCARADO,
    - que confirmar exija un mapeo previo y deje registro de quién decidió,
    - que los errores sean claros y nunca lancen.

Para tener un campo "por confirmar" se usa una copia de los datos en la que la
etiqueta "Número de cuenta" del caso de Ecuador se cambió por "Num. de cuenta".
"""

import json
from pathlib import Path

import pytest

from registro_proveedor.dominio.mapeo import cargar_mapeo
from registro_proveedor.herramientas.base import Contexto
from registro_proveedor.herramientas.proveedor import AYUDA_CASO, registro
from tests.ayudas import EditarJson, como_dict, como_lista

CUENTA = "03100012345"
CASO = "ec-corp-andina"


def _ejecutar(nombre: str, argumentos: dict[str, object], ctx: Contexto) -> dict[str, object]:
    """Ejecuta una herramienta y devuelve su respuesta tal como la vería el modelo."""
    respuesta = json.loads(registro.ejecutar(nombre, argumentos, ctx).a_json())
    assert isinstance(respuesta, dict)
    return respuesta


def _texto(ctx: Contexto, nombre: str, argumentos: dict[str, object]) -> str:
    return registro.ejecutar(nombre, argumentos, ctx).a_json()


@pytest.fixture
def ctx_con_pendiente(contexto: Contexto, datos: Path, editar_json: EditarJson) -> Contexto:
    """Contexto sobre una copia de los datos con un campo por confirmar en el caso de Ecuador."""

    def cambiar_etiqueta(campos: object) -> object:
        lista = como_lista(campos)
        return [
            {**como_dict(c), "etiqueta": "Num. de cuenta"}
            if como_dict(c)["etiqueta"] == "Número de cuenta"
            else c
            for c in lista
        ]

    editar_json(f"casos/{CASO}/plantilla-campos.json", cambiar_etiqueta)
    return Contexto(
        datos=datos,
        salida=contexto.salida,
        fecha_ejecucion=contexto.fecha_ejecucion,
        sesion_id=contexto.sesion_id,
        reloj=contexto.reloj,
    )


# ---------- proveedor_mapear_campos ----------


def test_mapear_agrupa_por_estado(contexto: Contexto) -> None:
    r = _ejecutar("proveedor_mapear_campos", {"caso": CASO}, contexto)
    assert r["ok"] is True
    datos = como_dict(r["data"])
    assert len(como_lista(datos["llenos"])) == 14
    faltantes = como_lista(datos["faltantes"])
    assert [como_dict(c)["etiqueta"] for c in faltantes] == ["Número de contribuyente especial"]
    assert datos["requiere_confirmacion"] == []
    assert datos["archivo"] == f"out/{CASO}/mapeo.json"
    assert datos["version_maestro"] == "sin versión"


def test_mapear_guarda_el_archivo_con_valores_completos(contexto: Contexto) -> None:
    registro.ejecutar("proveedor_mapear_campos", {"caso": CASO}, contexto)
    archivo = contexto.salida / CASO / "mapeo.json"
    assert CUENTA in archivo.read_text(encoding="utf-8")


def test_el_modelo_no_ve_la_cuenta_completa(contexto: Contexto) -> None:
    texto = _texto(contexto, "proveedor_mapear_campos", {"caso": CASO})
    assert CUENTA not in texto
    assert "****2345" in texto


def test_mapear_deja_registro(contexto: Contexto) -> None:
    registro.ejecutar("proveedor_mapear_campos", {"caso": CASO}, contexto)
    linea = json.loads((contexto.salida / CASO / "log.jsonl").read_text(encoding="utf-8"))
    assert linea["herramienta"] == "proveedor_mapear_campos"
    assert linea["resumen"] == "14 llenos · 1 faltantes · 0 por confirmar"


def test_mapear_caso_inexistente(contexto: Contexto) -> None:
    r = _ejecutar("proveedor_mapear_campos", {"caso": "no-existe"}, contexto)
    assert r["ok"] is False
    assert r["error"] == f"no existe el caso «no-existe». {AYUDA_CASO}"


def test_mapeo_anterior_danado_no_impide_mapear(contexto: Contexto) -> None:
    carpeta = contexto.carpeta_de_salida(CASO)
    (carpeta / "mapeo.json").write_text("{roto", encoding="utf-8")
    r = _ejecutar("proveedor_mapear_campos", {"caso": CASO}, contexto)
    assert r["ok"] is True
    assert como_dict(r["data"])["avisos"] == [
        "el mapeo anterior estaba dañado: no se conservaron sus confirmaciones"
    ]
    assert cargar_mapeo(carpeta) is not None  # se reemplazó por uno sano


# ---------- proveedor_confirmar_campo ----------


def test_confirmar_sin_mapeo_previo(contexto: Contexto) -> None:
    r = _ejecutar(
        "proveedor_confirmar_campo",
        {"caso": CASO, "etiqueta": "Banco", "decision": "aceptar"},
        contexto,
    )
    assert r["ok"] is False
    assert "primero use proveedor_mapear_campos" in str(r["error"])


def test_aceptar_un_campo_pendiente(ctx_con_pendiente: Contexto) -> None:
    ctx = ctx_con_pendiente
    r = _ejecutar("proveedor_mapear_campos", {"caso": CASO}, ctx)
    pendientes = como_lista(como_dict(r["data"])["requiere_confirmacion"])
    assert [como_dict(c)["etiqueta"] for c in pendientes] == ["Num. de cuenta"]

    texto = _texto(
        ctx,
        "proveedor_confirmar_campo",
        {"caso": CASO, "etiqueta": "Num. de cuenta", "decision": "aceptar"},
    )
    respuesta = json.loads(texto)
    assert respuesta["ok"] is True
    campo = respuesta["data"]["campo"]
    assert campo["estado"] == "lleno"
    assert campo["valor"] == "****2345"  # enmascarado para el modelo...
    assert campo["confirmacion"]["valor_propuesto"] == "****2345"  # ...también aquí
    assert CUENTA not in texto
    # Antes: 13 llenos · 1 faltante · 1 por confirmar. Después de aceptar, el pendiente
    # pasa a lleno (el faltante "Número de contribuyente especial" sigue igual).
    assert respuesta["data"]["resumen"] == "14 llenos · 1 faltantes · 0 por confirmar"

    # ...pero completo en mapeo.json, con quién y cuándo lo decidió.
    guardado = cargar_mapeo(ctx.salida / CASO)
    assert guardado is not None
    cuenta = next(c for c in guardado.campos if c.etiqueta == "Num. de cuenta")
    assert cuenta.valor == CUENTA
    assert cuenta.confirmacion is not None
    assert cuenta.confirmacion.por == "analista"
    assert cuenta.confirmacion.en == ctx.reloj()


def test_volver_a_mapear_conserva_la_confirmacion(ctx_con_pendiente: Contexto) -> None:
    ctx = ctx_con_pendiente
    registro.ejecutar("proveedor_mapear_campos", {"caso": CASO}, ctx)
    registro.ejecutar(
        "proveedor_confirmar_campo",
        {"caso": CASO, "etiqueta": "Num. de cuenta", "decision": "dejar_faltante"},
        ctx,
    )
    r = _ejecutar("proveedor_mapear_campos", {"caso": CASO}, ctx)
    faltantes = como_lista(como_dict(r["data"])["faltantes"])
    assert "Num. de cuenta" in [como_dict(c)["etiqueta"] for c in faltantes]


def test_confirmar_un_campo_lleno_da_error_claro(contexto: Contexto) -> None:
    registro.ejecutar("proveedor_mapear_campos", {"caso": CASO}, contexto)
    r = _ejecutar(
        "proveedor_confirmar_campo",
        {"caso": CASO, "etiqueta": "Banco", "decision": "aceptar"},
        contexto,
    )
    assert r["ok"] is False
    assert "solo se confirman los campos en requiere_confirmacion" in str(r["error"])


def test_decision_invalida(contexto: Contexto) -> None:
    r = _ejecutar(
        "proveedor_confirmar_campo",
        {"caso": CASO, "etiqueta": "Banco", "decision": "tal vez"},
        contexto,
    )
    assert r["ok"] is False
    assert "«decision»: el valor «tal vez» no es válido" in str(r["error"])
