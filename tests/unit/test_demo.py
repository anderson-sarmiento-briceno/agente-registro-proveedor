"""Pruebas de la demostración sin modelo (`registro_proveedor/demo.py` y `scripts/demo.py`).

Lo que se comprueba:
    - Criterio del Paso 9: dos ejecuciones con la misma fecha dan EXACTAMENTE el mismo
      resultado (todos los archivos, byte por byte, salvo los log.jsonl, que guardan
      cuánto tardó cada llamada) y sin ninguna clave de LLM.
    - Que nunca se cargue el SDK de Anthropic.
    - Que limpiar la salida no pueda borrar una carpeta equivocada.
    - Los códigos de salida y la elección de la fecha.
El contenido de cada caso se compara en tests/golden/.
"""

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from registro_proveedor.config import RAIZ_PROYECTO, Configuracion
from registro_proveedor.demo import (
    ErrorDeDemo,
    ejecutar_demo,
    elegir_fecha,
    main,
    preparar_salida,
)
from tests.ayudas import DATOS_REALES, FECHA_FIJA


def _archivos(carpeta: Path) -> dict[str, bytes]:
    """Todos los archivos de la carpeta (salvo los logs) con su contenido en bytes."""
    return {
        p.relative_to(carpeta).as_posix(): p.read_bytes()
        for p in sorted(carpeta.rglob("*"))
        if p.is_file() and p.name != "log.jsonl"
    }


# ---------- Criterio del Paso 9 ----------


def test_dos_ejecuciones_dan_exactamente_lo_mismo(tmp_path: Path) -> None:
    primera = ejecutar_demo(DATOS_REALES, tmp_path / "a" / "out", FECHA_FIJA)
    segunda = ejecutar_demo(DATOS_REALES, tmp_path / "b" / "out", FECHA_FIJA)
    assert primera == segunda  # mismo código y mismo texto
    archivos_a = _archivos(tmp_path / "a" / "out")
    archivos_b = _archivos(tmp_path / "b" / "out")
    assert archivos_a.keys() == archivos_b.keys()
    distintos = [nombre for nombre in archivos_a if archivos_a[nombre] != archivos_b[nombre]]
    assert distintos == []  # incluye el Excel, el PDF y las huellas del manifiesto


def test_procesa_los_4_casos_sin_errores(tmp_path: Path) -> None:
    resultado = ejecutar_demo(DATOS_REALES, tmp_path / "out", FECHA_FIJA)
    assert resultado.codigo == 0
    assert resultado.texto.endswith(
        "Resultado: 4 casos procesados · 1 listo para firma · 3 no listos · 0 con error"
    )
    for caso in (
        "co-industrias-delta",
        "ec-corp-andina",
        "hn-agroexport-sula",
        "pa-logistica-istmo",
    ):
        assert (tmp_path / "out" / caso / "paquete" / "manifiesto.json").is_file()


def test_sin_modelo_de_lenguaje(tmp_path: Path) -> None:
    """Se ejecuta en un proceso aparte, SIN clave, y se revisa que no se cargó `anthropic`."""
    codigo = (
        "import sys\n"
        "from registro_proveedor.demo import main\n"
        f"r = main(['--salida', {str(tmp_path / 'out')!r}])\n"
        "print('CODIGO', r.codigo)\n"
        "print('ANTHROPIC_CARGADO' if 'anthropic' in sys.modules else 'SIN_ANTHROPIC')\n"
    )
    entorno = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    proceso = subprocess.run(
        [sys.executable, "-c", codigo],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=entorno,
        cwd=tmp_path,  # lejos del .env del proyecto
        check=False,
    )
    assert "CODIGO 0" in proceso.stdout, proceso.stderr
    assert "SIN_ANTHROPIC" in proceso.stdout


# ---------- Limpiar la salida ----------


def test_limpia_lo_que_habia_en_out(tmp_path: Path) -> None:
    salida = tmp_path / "out"
    (salida / "viejo").mkdir(parents=True)
    (salida / "viejo" / "archivo.txt").write_text("de antes", encoding="utf-8")
    preparar_salida(salida)
    assert salida.is_dir() and list(salida.iterdir()) == []


@pytest.mark.parametrize("nombre", ["datos", "salida", "Out2"])
def test_no_borra_una_carpeta_que_no_se_llama_out(tmp_path: Path, nombre: str) -> None:
    peligrosa = tmp_path / nombre
    peligrosa.mkdir()
    (peligrosa / "valioso.txt").write_text("no me borres", encoding="utf-8")
    with pytest.raises(ErrorDeDemo, match="debe llamarse «out»"):
        preparar_salida(peligrosa)
    assert (peligrosa / "valioso.txt").exists()


def test_main_con_salida_peligrosa_no_borra_nada(tmp_path: Path) -> None:
    (tmp_path / "importante.txt").write_text("x", encoding="utf-8")
    resultado = main(["--salida", str(tmp_path)])
    assert resultado.codigo == 1
    assert "debe llamarse «out»" in resultado.texto
    assert (tmp_path / "importante.txt").exists()


# ---------- Errores ----------


def test_caso_inexistente(tmp_path: Path) -> None:
    resultado = ejecutar_demo(DATOS_REALES, tmp_path / "out", FECHA_FIJA, ["no-existe"])
    assert resultado.codigo == 1
    assert "ERROR: no existe el caso «no-existe»" in resultado.texto


def test_un_caso_roto_no_detiene_a_los_demas(tmp_path: Path, datos: Path) -> None:
    (datos / "casos/ec-corp-andina/plantilla-campos.json").write_text("[", encoding="utf-8")
    resultado = ejecutar_demo(datos, tmp_path / "out", FECHA_FIJA)
    assert resultado.codigo == 1
    assert "ec-corp-andina\n  ERROR al leer: datos/casos/ec-corp-andina/plantilla-campos.json" in (
        resultado.texto
    )
    assert "Resultado: 3 casos procesados · 1 listo para firma · 2 no listos · 1 con error" in (
        resultado.texto
    )


def test_un_solo_caso(tmp_path: Path) -> None:
    resultado = main(["--caso", "co-industrias-delta", "--salida", str(tmp_path / "out")])
    assert resultado.codigo == 0
    assert "Resultado: 1 caso procesado · 1 listo para firma" in resultado.texto


# ---------- La fecha ----------


def _config(fecha: str | None = None) -> Configuracion:
    return Configuracion(_env_file=None, fecha_ejecucion=fecha)  # type: ignore[call-arg]


def test_fecha_por_defecto_es_la_de_hoy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Revisión de Anderson: la demo no inventa fechas de ejecución, usa la de hoy."""
    monkeypatch.delenv("FECHA_EJECUCION", raising=False)
    assert elegir_fecha(None, _config()) == date.today()


def test_la_fecha_del_env_se_usa_si_no_hay_argumento() -> None:
    assert elegir_fecha(None, _config("2026-10-15")) == date(2026, 10, 15)


def test_el_argumento_gana() -> None:
    assert elegir_fecha("2026-12-01", _config("2026-10-15")) == date(2026, 12, 1)
    assert elegir_fecha("hoy", _config("2026-10-15")) == date.today()


def test_fecha_invalida(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as salida:  # argparse termina con código 2
        main(["--fecha", "mañana", "--salida", str(tmp_path / "out")], _config())
    assert salida.value.code == 2


def test_a_la_fecha_de_la_revision_colombia_esta_listo(tmp_path: Path) -> None:
    """Con los datos de la revisión (2026-11-26), Colombia siempre funciona y los demás no.

    Así se ve lo que hace el agente: un caso que sale bien y tres con algo por resolver
    (un soporte ausente, uno vencido y un campo por confirmar).
    """
    resultado = ejecutar_demo(DATOS_REALES, tmp_path / "out", date(2026, 11, 26))
    assert "1 listo para firma · 3 no listos" in resultado.texto


def test_cuando_vence_la_camara_nada_esta_listo(tmp_path: Path) -> None:
    """La Cámara de Comercio vence el 2027-02-24 (90 días después de la revisión)."""
    resultado = ejecutar_demo(DATOS_REALES, tmp_path / "out", date(2027, 2, 25))
    assert "0 listos para firma · 4 no listos" in resultado.texto


# ---------- Matriz de llamadas (--llamadas) ----------


def _celdas(fila: str) -> list[str]:
    """Las celdas de una fila de tabla Markdown: "| a | b |" → ["a", "b"]."""
    return [c.strip() for c in fila.strip().strip("|").split("|")]


def test_matriz_de_llamadas(tmp_path: Path) -> None:
    """Una fila por caso y una columna por herramienta, en el orden en que se llaman."""
    salida = tmp_path / "out"
    resultado = main(["--llamadas", "--fecha", "2026-09-01", "--salida", str(salida)])
    assert resultado.codigo == 0
    archivo = (salida / "llamadas.md").read_text(encoding="utf-8")
    assert archivo.startswith("# Llamadas a herramientas · demo del 2026-09-01")
    assert "proveedor_listar_casos → ✓ 4 casos" in archivo

    filas = [f for f in archivo.splitlines() if f.startswith("| ")]
    encabezado, *casos = filas
    assert _celdas(encabezado) == [
        "Caso",
        "1. Leer solicitud",
        "2. Mapear campos",
        "3. Generar formulario",
        "4. Armar paquete",
    ]
    assert [_celdas(f)[0] for f in casos] == [
        "co-industrias-delta",
        "ec-corp-andina",
        "hn-agroexport-sula",
        "pa-logistica-istmo",
    ]
    assert _celdas(casos[3]) == [
        "pa-logistica-istmo",
        "✓ portal · 9 campos · 2 soportes",
        "✓ 8 llenos · 0 faltantes · 1 por confirmar",
        "✓ valores-portal.md",
        "✓ NO listo (1 motivo)",
    ]
    # Las 16 llamadas de los casos respondieron bien.
    assert all(c.startswith("✓") for f in casos for c in _celdas(f)[1:])
    assert "Llamadas a herramientas por caso:" in resultado.texto  # también en la terminal


def test_matriz_cuando_una_herramienta_falla(tmp_path: Path, datos: Path) -> None:
    """Si leer falla, la fila lo marca con ✗ y las demás herramientas quedan sin llamar (—)."""
    (datos / "casos/ec-corp-andina/plantilla-campos.json").write_text("[", encoding="utf-8")
    resultado = ejecutar_demo(datos, tmp_path / "out", FECHA_FIJA)
    fila = next(f for f in resultado.matriz.splitlines() if f.startswith("| ec-corp-andina"))
    assert _celdas(fila) == ["ec-corp-andina", "✗ error", "—", "—", "—"]


def test_la_matriz_sale_igual_en_dos_ejecuciones(tmp_path: Path) -> None:
    primera = ejecutar_demo(DATOS_REALES, tmp_path / "a" / "out", FECHA_FIJA)
    segunda = ejecutar_demo(DATOS_REALES, tmp_path / "b" / "out", FECHA_FIJA)
    assert primera.matriz == segunda.matriz != ""


def test_sin_la_opcion_no_hay_tabla(tmp_path: Path) -> None:
    resultado = main(["--salida", str(tmp_path / "out")])
    assert "Llamadas a herramientas" not in resultado.texto
    assert not (tmp_path / "out" / "llamadas.md").exists()


# ---------- scripts/demo.py ----------


def test_script_desde_la_terminal(tmp_path: Path) -> None:
    proceso = subprocess.run(
        [
            sys.executable,
            str(RAIZ_PROYECTO / "scripts" / "demo.py"),
            "--salida",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proceso.returncode == 0, proceso.stderr
    assert proceso.stdout.startswith("Demostración sin modelo de lenguaje · fecha de ejecución")
