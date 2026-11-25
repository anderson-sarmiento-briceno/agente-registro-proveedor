"""Pruebas de la herramienta proveedor_generar_formulario, como la llamará el agente.

Lo propio de la herramienta (los archivos ya se revisan en test_generadores.py):
    - exige un mapeo previo y que corresponda a la plantilla;
    - genera el archivo que pide el formato del caso;
    - responde sin ningún valor, con conteos y avisos claros;
    - deja su línea en log.jsonl.
"""

import json
from pathlib import Path

import pytest

from registro_proveedor.herramientas.base import Contexto
from registro_proveedor.herramientas.proveedor import AVISO_PORTAL, registro
from tests.ayudas import EditarJson, como_dict, como_lista


def _ejecutar(nombre: str, argumentos: dict[str, object], ctx: Contexto) -> dict[str, object]:
    respuesta = json.loads(registro.ejecutar(nombre, argumentos, ctx).a_json())
    assert isinstance(respuesta, dict)
    return respuesta


def _mapear_y_generar(caso: str, ctx: Contexto) -> dict[str, object]:
    assert _ejecutar("proveedor_mapear_campos", {"caso": caso}, ctx)["ok"] is True
    return _ejecutar("proveedor_generar_formulario", {"caso": caso}, ctx)


@pytest.mark.parametrize(
    ("caso", "archivo", "conteos"),
    [
        ("co-industrias-delta", "formulario.xlsx", (17, 0, 0)),
        ("ec-corp-andina", "formulario.pdf", (13, 1, 1)),
        ("hn-agroexport-sula", "formulario.xlsx", (9, 1, 1)),
        ("pa-logistica-istmo", "valores-portal.md", (8, 0, 1)),
    ],
)
def test_genera_los_4_casos(
    contexto: Contexto, caso: str, archivo: str, conteos: tuple[int, int, int]
) -> None:
    r = _mapear_y_generar(caso, contexto)
    assert r["ok"] is True
    datos = como_dict(r["data"])
    assert datos["archivo"] == f"out/{caso}/{archivo}"
    assert (datos["escritos"], datos["faltantes"], datos["pendientes"]) == conteos
    assert (contexto.salida / caso / archivo).is_file()


def test_la_respuesta_no_trae_valores(contexto: Contexto) -> None:
    texto = json.dumps(_mapear_y_generar("co-industrias-delta", contexto))
    for valor in ("Empresa Ejemplo", "900123456", "03100012345", "2345"):
        assert valor not in texto


def test_avisos(contexto: Contexto) -> None:
    portal = como_dict(_mapear_y_generar("pa-logistica-istmo", contexto)["data"])
    assert portal["avisos"] == [
        AVISO_PORTAL,
        "hay 1 campo por confirmar: quedó vacío en el formulario; "
        "después de confirmar, vuelva a generarlo",
    ]
    colombia = como_dict(_mapear_y_generar("co-industrias-delta", contexto)["data"])
    assert colombia["avisos"] == []


def test_confirmar_y_volver_a_generar(contexto: Contexto) -> None:
    _mapear_y_generar("ec-corp-andina", contexto)
    _ejecutar(
        "proveedor_confirmar_campo",
        {"caso": "ec-corp-andina", "etiqueta": "RUC", "decision": "aceptar"},
        contexto,
    )
    r = _ejecutar("proveedor_generar_formulario", {"caso": "ec-corp-andina"}, contexto)
    datos = como_dict(r["data"])
    assert (datos["escritos"], datos["pendientes"], datos["avisos"]) == (14, 0, [])


def test_deja_registro(contexto: Contexto) -> None:
    _mapear_y_generar("co-industrias-delta", contexto)
    lineas = (contexto.salida / "co-industrias-delta" / "log.jsonl").read_text(encoding="utf-8")
    ultima = json.loads(lineas.splitlines()[-1])
    assert ultima["herramienta"] == "proveedor_generar_formulario"
    assert ultima["resumen"] == (
        "out/co-industrias-delta/formulario.xlsx · 17 escritos · 0 faltantes · 0 pendientes"
    )


# ---------- Errores claros ----------


def test_sin_mapeo_previo(contexto: Contexto) -> None:
    r = _ejecutar("proveedor_generar_formulario", {"caso": "co-industrias-delta"}, contexto)
    assert r["ok"] is False
    assert "primero use proveedor_mapear_campos" in str(r["error"])


def test_mapeo_de_una_version_anterior(contexto: Contexto) -> None:
    """Un mapeo.json sin `celda_etiqueta` (de antes del Paso 7) pide volver a mapear."""
    _ejecutar("proveedor_mapear_campos", {"caso": "co-industrias-delta"}, contexto)
    archivo = contexto.salida / "co-industrias-delta" / "mapeo.json"
    viejo = json.loads(archivo.read_text(encoding="utf-8"))
    for campo in viejo["campos"]:
        del campo["celda_etiqueta"]
    archivo.write_text(json.dumps(viejo), encoding="utf-8")

    r = _ejecutar("proveedor_generar_formulario", {"caso": "co-industrias-delta"}, contexto)
    assert r["ok"] is False
    assert "es de una versión anterior: vuelva a usar proveedor_mapear_campos" in str(r["error"])


def test_plantilla_cambiada_despues_de_mapear(
    contexto: Contexto, datos: Path, editar_json: EditarJson
) -> None:
    ctx = Contexto(
        datos=datos,
        salida=contexto.salida,
        fecha_ejecucion=contexto.fecha_ejecucion,
        reloj=contexto.reloj,
    )
    _ejecutar("proveedor_mapear_campos", {"caso": "co-industrias-delta"}, ctx)

    def mover(celdas: object) -> object:
        lista = como_lista(celdas)
        lista[0] = {**como_dict(lista[0]), "celda_valor": "D3"}
        return lista

    editar_json("casos/co-industrias-delta/plantilla-celdas.json", mover)
    r = _ejecutar("proveedor_generar_formulario", {"caso": "co-industrias-delta"}, ctx)
    assert r["ok"] is False
    assert "no corresponde a la plantilla actual" in str(r["error"])
    assert not (contexto.salida / "co-industrias-delta" / "formulario.xlsx").exists()


def test_caso_inexistente(contexto: Contexto) -> None:
    r = _ejecutar("proveedor_generar_formulario", {"caso": "no-existe"}, contexto)
    assert r["ok"] is False
    assert "no existe el caso «no-existe»" in str(r["error"])
