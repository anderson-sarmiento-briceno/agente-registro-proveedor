"""Configuración del proyecto, leída de variables de entorno o del archivo `.env`.

El resto del código pide la configuración con `cargar_configuracion()` y nunca
lee `os.environ` directamente.
"""

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Raíz del proyecto: config.py está en src/registro_proveedor/, dos niveles abajo.
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]


class Configuracion(BaseSettings):
    """Variables de entorno del proyecto. Ver `.env.example`."""

    model_config = SettingsConfigDict(
        env_file=RAIZ_PROYECTO / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Una variable vacía (como `FECHA_EJECUCION=` en .env.example) se trata como
        # si no existiera, en lugar de fallar al convertir "" en fecha.
        env_ignore_empty=True,
    )

    # Opcional: el núcleo funciona sin clave (scripts/demo.py no la usa).
    # SecretStr evita que la clave aparezca si alguien imprime la configuración.
    anthropic_api_key: SecretStr | None = None
    llm_modelo: str = Field(default="claude-haiku-5-5", min_length=1)

    # RN7: fecha de ejecución inyectable. Si está vacía se usa la fecha de hoy.
    fecha_ejecucion: date | None = None

    nivel_log: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    def hay_clave_llm(self) -> bool:
        """Indica si hay una clave de Anthropic configurada (sin revelarla)."""
        return (
            self.anthropic_api_key is not None and self.anthropic_api_key.get_secret_value() != ""
        )

    def fecha_efectiva(self) -> date:
        """Devuelve la fecha inyectada o, si no hay, la de hoy."""
        return self.fecha_ejecucion or date.today()


def cargar_configuracion() -> Configuracion:
    """Lee la configuración desde el entorno y `.env`."""
    return Configuracion()
