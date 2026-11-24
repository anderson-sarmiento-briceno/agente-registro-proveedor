"""Pruebas del Paso 1: el paquete se importa y la configuración carga bien."""

from datetime import date
from pathlib import Path

import pytest

from registro_proveedor.config import RAIZ_PROYECTO, Configuracion


def _config_sin_env(**valores: object) -> Configuracion:
    """Crea la configuración sin leer el `.env` real, para que la prueba no dependa de él."""
    return Configuracion(_env_file=None, **valores)  # type: ignore[call-arg]


def test_el_paquete_se_importa() -> None:
    import registro_proveedor

    assert registro_proveedor.__doc__


def test_carga_sin_clave(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = _config_sin_env()
    assert config.hay_clave_llm() is False
    assert config.llm_modelo == "claude-haiku-5-5"


def test_la_clave_no_se_muestra() -> None:
    config = _config_sin_env(anthropic_api_key="clave-de-prueba")
    assert config.hay_clave_llm() is True
    assert "clave-de-prueba" not in repr(config)
    assert "clave-de-prueba" not in str(config.anthropic_api_key)


def test_env_example_copiado_tal_cual_funciona(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si alguien copia .env.example como .env sin llenarlo, la configuración igual carga."""
    for nombre in ("ANTHROPIC_API_KEY", "LLM_MODELO", "FECHA_EJECUCION", "NIVEL_LOG"):
        monkeypatch.delenv(nombre, raising=False)
    archivo = tmp_path / ".env"
    ejemplo = RAIZ_PROYECTO / ".env.example"
    archivo.write_text(ejemplo.read_text(encoding="utf-8"), encoding="utf-8")

    config = Configuracion(_env_file=archivo)  # type: ignore[call-arg]

    assert config.fecha_ejecucion is None
    assert config.hay_clave_llm() is False


def test_fecha_inyectada() -> None:
    config = _config_sin_env(fecha_ejecucion="2026-03-15")
    assert config.fecha_efectiva() == date(2026, 3, 15)
