"""Pruebas de la herramienta proveedor_armar_paquete, como la llamará el agente.

El contenido del paquete ya se prueba en test_paquete.py. Aquí: que exija un mapeo,
que responda si está listo y por qué, sin valores, y que deje su línea en el log.
"""

import json

from registro_proveedor.herramientas.base import Contexto
from registro_proveedor.herramientas.proveedor import registro
from tests.ayudas import aprobado, como_dict, como_lista


def _ejecutar(nombre: str, argumentos: dict[str, object], ctx: Contexto) -> dict[str, object]:
    respuesta = json.loads(registro.ejecutar(nombre, argumentos, ctx).a_json())
    assert isinstance(respuesta, dict)
    return respuesta


def _mapear_y_armar(caso: str, ctx: Contexto) -> dict[str, object]:
    assert _ejecutar("proveedor_mapear_campos", {"caso": caso}, ctx)["ok"] is True
    return _ejecutar("proveedor_armar_paquete", {"caso": caso}, ctx)


def test_paquete_listo(contexto: Contexto) -> None:
    r = _mapear_y_armar("co-industrias-delta", contexto)
    assert r["ok"] is True
    datos = como_dict(r["data"])
    assert datos["carpeta"] == "out/co-industrias-delta/paquete"
    assert datos["listo_para_firma"] is True
    assert datos["motivos"] == []
    assert "manifiesto.json" in como_lista(datos["archivos"])
    assert (contexto.salida / "co-industrias-delta" / "paquete" / "checklist.md").is_file()


def test_paquete_no_listo_dice_por_que(contexto: Contexto) -> None:
    datos = como_dict(_mapear_y_armar("hn-agroexport-sula", contexto)["data"])
    assert datos["listo_para_firma"] is False
    assert datos["motivos"] == [
        "soporte vencido: Certificación de parafiscales, venció el 2026-08-31 (hace 1 día)",
        "campo por confirmar: «RTN»",
    ]
    estados = {como_dict(s)["tipo"]: como_dict(s)["estado"] for s in como_lista(datos["soportes"])}
    assert estados == {"camara_comercio": "presente", "rut": "presente", "parafiscales": "vencido"}


def test_la_respuesta_no_trae_valores(contexto: Contexto) -> None:
    texto = json.dumps(_mapear_y_armar("co-industrias-delta", contexto))
    for valor in ("03100012345", "71555123", "900123456", "COLOCOBM"):
        assert valor not in texto


def test_confirmar_y_volver_a_armar(contexto: Contexto) -> None:
    _mapear_y_armar("pa-logistica-istmo", contexto)
    argumentos: dict[str, object] = {
        "caso": "pa-logistica-istmo",
        "etiqueta": "RUC",
        "decision": "aceptar",
    }
    confirmar = "proveedor_confirmar_campo"
    assert _ejecutar(confirmar, argumentos, aprobado(contexto, confirmar, argumentos))["ok"]
    r = _ejecutar("proveedor_armar_paquete", {"caso": "pa-logistica-istmo"}, contexto)
    assert como_dict(r["data"])["listo_para_firma"] is True


def test_deja_registro(contexto: Contexto) -> None:
    _mapear_y_armar("hn-agroexport-sula", contexto)
    lineas = (contexto.salida / "hn-agroexport-sula" / "log.jsonl").read_text(encoding="utf-8")
    ultima = json.loads(lineas.splitlines()[-1])
    assert ultima["herramienta"] == "proveedor_armar_paquete"
    assert ultima["resumen"] == "out/hn-agroexport-sula/paquete · NO listo: 2 motivos"


def test_sin_mapeo_previo(contexto: Contexto) -> None:
    r = _ejecutar("proveedor_armar_paquete", {"caso": "co-industrias-delta"}, contexto)
    assert r["ok"] is False
    assert "primero use proveedor_mapear_campos" in str(r["error"])


def test_caso_inexistente(contexto: Contexto) -> None:
    r = _ejecutar("proveedor_armar_paquete", {"caso": "no-existe"}, contexto)
    assert r["ok"] is False
    assert "no existe el caso «no-existe»" in str(r["error"])
