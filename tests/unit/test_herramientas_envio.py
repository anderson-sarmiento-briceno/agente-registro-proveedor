"""Pruebas de la herramienta proveedor_simular_envio (Paso 13, HU-5).

Lo que se comprueba:
    - sin aprobación de la analista, no escribe nada (doble candado);
    - con aprobación, escribe ENVIO-SIMULADO.md con los archivos, sus huellas y quién
      aprobó, y sin ningún dato bancario;
    - se niega si no hay paquete, si no está listo para firma o si quedó desactualizado
      (otra fecha, el mapeo cambió o un archivo cambió).

La fecha fija de las pruebas (2026-09-01) deja listo el caso de Colombia; Panamá queda
listo después de aceptar su RUC.
"""

import dataclasses
import json
from datetime import date

from registro_proveedor.herramientas.base import SIN_APROBACION, Contexto
from registro_proveedor.herramientas.proveedor import registro
from tests.ayudas import aprobado, como_dict

CO = "co-industrias-delta"
EC = "ec-corp-andina"
PA = "pa-logistica-istmo"
ENVIAR = "proveedor_simular_envio"
CONFIRMAR = "proveedor_confirmar_campo"


def _ejecutar(nombre: str, argumentos: dict[str, object], ctx: Contexto) -> dict[str, object]:
    respuesta = json.loads(registro.ejecutar(nombre, argumentos, ctx).a_json())
    assert isinstance(respuesta, dict)
    return respuesta


def _armar(caso: str, ctx: Contexto) -> None:
    assert _ejecutar("proveedor_mapear_campos", {"caso": caso}, ctx)["ok"] is True
    assert _ejecutar("proveedor_armar_paquete", {"caso": caso}, ctx)["ok"] is True


def _enviar(caso: str, ctx: Contexto) -> dict[str, object]:
    """Simula el envío CON la aprobación de la analista."""
    return _ejecutar(ENVIAR, {"caso": caso}, aprobado(ctx, ENVIAR, {"caso": caso}))


def _confirmar_ruc(caso: str, decision: str, ctx: Contexto) -> None:
    argumentos: dict[str, object] = {"caso": caso, "etiqueta": "RUC", "decision": decision}
    assert _ejecutar(CONFIRMAR, argumentos, aprobado(ctx, CONFIRMAR, argumentos))["ok"] is True


def test_sin_aprobacion_no_escribe_nada(contexto: Contexto) -> None:
    _armar(CO, contexto)
    r = _ejecutar(ENVIAR, {"caso": CO}, contexto)
    assert r == {"ok": False, "data": None, "error": SIN_APROBACION}
    assert not (contexto.salida / CO / "ENVIO-SIMULADO.md").exists()


def test_envio_de_un_paquete_listo(contexto: Contexto) -> None:
    _armar(CO, contexto)
    r = _enviar(CO, contexto)
    assert r["ok"] is True
    datos = como_dict(r["data"])
    assert datos == {
        "caso": CO,
        "archivo": f"out/{CO}/ENVIO-SIMULADO.md",
        "archivos_enviados": 8,  # formulario, 4 soportes, checklist, borrador y manifiesto
        "aprobacion": "aprobacion-de-prueba",
    }
    texto = (contexto.salida / CO / "ENVIO-SIMULADO.md").read_text(encoding="utf-8")
    assert "**No se envió nada.**" in texto
    assert "aprobación `aprobacion-de-prueba`" in texto
    assert "Aprobado por:** analista" in texto
    assert "| `manifiesto.json` |" in texto
    for dato_bancario in ("03100012345", "COLOCOBM"):
        assert dato_bancario not in texto


def test_deja_la_aprobacion_en_el_log(contexto: Contexto) -> None:
    _armar(CO, contexto)
    _enviar(CO, contexto)
    lineas = (contexto.salida / CO / "log.jsonl").read_text(encoding="utf-8").splitlines()
    ultima = json.loads(lineas[-1])
    assert ultima["herramienta"] == ENVIAR
    assert ultima["ok"] is True
    assert ultima["aprobacion"] == "aprobacion-de-prueba"
    assert ultima["resumen"] == (
        f"out/{CO}/ENVIO-SIMULADO.md · 8 archivos · aprobación aprobacion-de-prueba"
    )


def test_sin_paquete(contexto: Contexto) -> None:
    assert _ejecutar("proveedor_mapear_campos", {"caso": CO}, contexto)["ok"] is True
    r = _enviar(CO, contexto)
    assert r["ok"] is False
    assert "todavía no tiene paquete: primero use proveedor_armar_paquete" in str(r["error"])


def test_paquete_no_listo(contexto: Contexto) -> None:
    _armar(EC, contexto)
    r = _enviar(EC, contexto)
    assert r["ok"] is False
    error = str(r["error"])
    assert error.startswith("el paquete no está listo para firma, así que no se puede enviar")
    assert "campo por confirmar: «RUC»" in error
    assert not (contexto.salida / EC / "ENVIO-SIMULADO.md").exists()


def test_paquete_armado_con_otra_fecha(contexto: Contexto) -> None:
    _armar(CO, contexto)
    otro_dia = dataclasses.replace(contexto, fecha_ejecucion=date(2026, 9, 2))
    r = _enviar(CO, otro_dia)
    assert r["ok"] is False
    assert "se armó con la fecha 2026-09-01" in str(r["error"])


def test_el_mapeo_cambio_despues_de_armar(contexto: Contexto) -> None:
    """Panamá: se acepta el RUC, se arma (listo) y DESPUÉS la analista cambia de opinión."""
    assert _ejecutar("proveedor_mapear_campos", {"caso": PA}, contexto)["ok"] is True
    _confirmar_ruc(PA, "aceptar", contexto)
    assert _ejecutar("proveedor_armar_paquete", {"caso": PA}, contexto)["ok"] is True
    _confirmar_ruc(PA, "dejar_faltante", contexto)
    r = _enviar(PA, contexto)
    assert r["ok"] is False
    assert "el mapeo cambió después de armar el paquete" in str(r["error"])


def test_un_archivo_del_paquete_cambio(contexto: Contexto) -> None:
    _armar(CO, contexto)
    checklist = contexto.salida / CO / "paquete" / "checklist.md"
    checklist.write_text(checklist.read_text(encoding="utf-8") + "\nañadido\n", encoding="utf-8")
    r = _enviar(CO, contexto)
    assert r["ok"] is False
    assert "el archivo «checklist.md» del paquete cambió o falta" in str(r["error"])


def test_manifiesto_danado(contexto: Contexto) -> None:
    _armar(CO, contexto)
    (contexto.salida / CO / "paquete" / "manifiesto.json").write_text("{roto", encoding="utf-8")
    r = _enviar(CO, contexto)
    assert r["ok"] is False
    assert "el manifiesto del paquete está dañado" in str(r["error"])
