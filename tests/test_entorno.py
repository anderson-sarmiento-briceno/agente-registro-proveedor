"""Pruebas del Paso 1: el paquete se importa y la configuración (`config.py`) carga bien.

Ninguna prueba lee el `.env` real del computador: así el resultado no depende de si
alguien puso su clave o no. Para eso se usa `_env_file=None` (no leer ningún .env) o
un `.env` temporal, y `monkeypatch.delenv` para quitar variables del entorno solo
durante la prueba (pytest las restaura al terminar).
"""

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from registro_proveedor.config import RAIZ_PROYECTO, Configuracion


def _config_sin_env(**valores: object) -> Configuracion:
    """Crea la configuración sin leer el `.env` real, para que la prueba no dependa de él."""
    # `_env_file` es un parámetro especial de pydantic-settings que mypy no conoce
    # (no es un campo del modelo); por eso se silencia ese aviso puntual.
    return Configuracion(_env_file=None, **valores)  # type: ignore[call-arg]


def test_el_paquete_se_importa() -> None:
    import registro_proveedor

    assert registro_proveedor.__doc__


def test_carga_sin_clave(monkeypatch: pytest.MonkeyPatch) -> None:
    """El núcleo debe funcionar sin clave de Anthropic (principio 7)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = _config_sin_env()
    assert config.hay_clave_llm() is False
    assert config.llm_modelo == "claude-haiku-5-5"


def test_la_clave_no_se_muestra() -> None:
    """Aunque se imprima la configuración, la clave no aparece (SecretStr)."""
    config = _config_sin_env(anthropic_api_key="clave-de-prueba")
    assert config.hay_clave_llm() is True
    assert "clave-de-prueba" not in repr(config)
    assert "clave-de-prueba" not in str(config.anthropic_api_key)


def test_env_example_copiado_tal_cual_funciona(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si alguien copia .env.example como .env sin llenarlo, la configuración igual carga.

    Esta prueba nació de un error real: `FECHA_EJECUCION=` vacía hacía fallar la
    conversión a fecha. Se corrigió con `env_ignore_empty=True` en config.py.
    """
    for nombre in ("ANTHROPIC_API_KEY", "LLM_MODELO", "FECHA_EJECUCION", "NIVEL_LOG"):
        monkeypatch.delenv(nombre, raising=False)
    archivo = tmp_path / ".env"
    ejemplo = RAIZ_PROYECTO / ".env.example"
    archivo.write_text(ejemplo.read_text(encoding="utf-8"), encoding="utf-8")

    config = Configuracion(_env_file=archivo)  # type: ignore[call-arg]

    assert config.fecha_ejecucion is None
    assert config.hay_clave_llm() is False


def test_fecha_inyectada() -> None:
    """RN7: con una fecha fija, el resultado no depende del día en que se ejecuta."""
    config = _config_sin_env(fecha_ejecucion="2026-03-15")
    assert config.fecha_efectiva() == date(2026, 3, 15)


def test_sin_fecha_inyectada_se_usa_la_de_hoy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FECHA_EJECUCION", raising=False)
    assert _config_sin_env().fecha_efectiva() == date.today()


def test_nivel_de_log_invalido_se_rechaza() -> None:
    with pytest.raises(ValidationError, match="nivel_log"):
        _config_sin_env(nivel_log="MUCHO")
