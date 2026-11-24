"""Pruebas de `observabilidad.py`: enmascaramiento, log de auditoría y logs de operación."""

import json
from pathlib import Path

import pytest

from registro_proveedor.observabilidad import (
    RegistroLlamada,
    configurar_logs,
    enmascarar,
    enmascarar_datos,
    es_ruta_sensible,
    escribir_auditoria,
    obtener_logger,
    procesador_enmascarar,
)
from tests.ayudas import HORA_FIJA

# ---------- Enmascaramiento (RN8) ----------


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("03100012345", "****2345"),  # caso normal: se ven los últimos 4
        ("71555123", "****5123"),
        ("12345", "****2345"),
        ("1234", "****"),  # 4 o menos: se oculta entero (si no, se vería completo)
        ("", "****"),
        (71555123, "****5123"),  # un número también se enmascara
    ],
)
def test_enmascarar(valor: object, esperado: str) -> None:
    assert enmascarar(valor) == esperado


def test_enmascarar_datos_recorre_todo_y_no_modifica_el_original() -> None:
    original = {
        "nit": "900123456",  # el NIT es de la empresa: NO se enmascara
        "banco": {"numero_cuenta": "03100012345", "nombre": "Bancolombia S.A."},
        "personas": [{"identificacion": "71555123", "nombre": "Roberto"}],
        "vacio": {"numero_cuenta": None},  # un valor vacío se deja como está
    }
    assert enmascarar_datos(original) == {
        "nit": "900123456",
        "banco": {"numero_cuenta": "****2345", "nombre": "Bancolombia S.A."},
        "personas": [{"identificacion": "****5123", "nombre": "Roberto"}],
        "vacio": {"numero_cuenta": None},
    }
    assert original["banco"] == {"numero_cuenta": "03100012345", "nombre": "Bancolombia S.A."}


def test_rutas_sensibles() -> None:
    assert es_ruta_sensible("banco.numero_cuenta")
    assert es_ruta_sensible("representante_legal.identificacion")
    assert not es_ruta_sensible("nit")
    assert not es_ruta_sensible("banco.nombre")


# ---------- Auditoría: log.jsonl ----------


def _registro(caso: str | None, resumen: str = "ok") -> RegistroLlamada:
    return RegistroLlamada(
        ts=HORA_FIJA,
        sesion="s1",
        herramienta="proveedor_x",
        caso=caso,
        ok=True,
        resumen=resumen,
        duracion_ms=3,
    )


def _lineas(archivo: Path) -> list[dict[str, object]]:
    return [json.loads(linea) for linea in archivo.read_text(encoding="utf-8").splitlines()]


def test_auditoria_global_y_por_caso(tmp_path: Path) -> None:
    escribir_auditoria(tmp_path, _registro("ec-corp-andina"))
    escribir_auditoria(tmp_path, _registro(None))

    # El log global tiene las dos llamadas; el del caso, solo la suya.
    assert len(_lineas(tmp_path / "log.jsonl")) == 2
    del_caso = _lineas(tmp_path / "ec-corp-andina" / "log.jsonl")
    assert del_caso == [
        {
            "ts": "2026-09-01T12:00:00Z",
            "sesion": "s1",
            "herramienta": "proveedor_x",
            "caso": "ec-corp-andina",
            "ok": True,
            "resumen": "ok",
            "duracion_ms": 3,
        }
    ]


def test_auditoria_agrega_sin_borrar(tmp_path: Path) -> None:
    for _ in range(3):
        escribir_auditoria(tmp_path, _registro(None))
    assert len(_lineas(tmp_path / "log.jsonl")) == 3


def test_si_no_se_puede_escribir_no_se_interrumpe(tmp_path: Path) -> None:
    """Si `out/` es un archivo (y no una carpeta), escribir falla, pero sin excepción."""
    salida = tmp_path / "out"
    salida.write_text("no soy una carpeta", encoding="utf-8")
    escribir_auditoria(salida, _registro("ec-corp-andina"))  # no debe lanzar


# ---------- Logs de operación (structlog) ----------


def test_procesador_enmascara_el_evento() -> None:
    evento = {"event": "x", "numero_cuenta": "03100012345"}
    assert procesador_enmascarar(None, "info", evento) == {
        "event": "x",
        "numero_cuenta": "****2345",
    }


def test_logs_de_operacion_en_json_y_enmascarados(capsys: pytest.CaptureFixture[str]) -> None:
    # `capsys` captura lo que se escribe en la terminal (stdout y stderr).
    configurar_logs("INFO")
    obtener_logger().info("prueba", numero_cuenta="03100012345")
    obtener_logger().debug("no_debe_salir")  # por debajo del nivel INFO

    salida = capsys.readouterr().err.strip().splitlines()
    assert len(salida) == 1
    evento = json.loads(salida[0])
    assert evento["event"] == "prueba"
    assert evento["level"] == "info"
    assert evento["numero_cuenta"] == "****2345"


def test_excepciones_sin_variables_locales(capsys: pytest.CaptureFixture[str]) -> None:
    """El detalle de un error no incluye los valores de las variables (podrían ser sensibles)."""
    configurar_logs("INFO")
    secreto = "03100012345"
    try:
        raise RuntimeError("fallo de prueba")
    except RuntimeError:
        obtener_logger().exception("error")
    texto = capsys.readouterr().err
    assert "fallo de prueba" in texto  # el error sí aparece
    assert secreto not in texto  # el valor de la variable local, no
