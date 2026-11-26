"""Configuración del proyecto, leída de variables de entorno o del archivo `.env`.

¿Qué problema resuelve?
    El programa necesita algunos datos que cambian según dónde se ejecute: la clave
    de Anthropic, el modelo a usar, una fecha fija para las pruebas, el nivel de logs.
    Esos datos no se escriben en el código: se leen de variables de entorno.

¿Cómo funciona?
    `Configuracion` hereda de `BaseSettings` (librería pydantic-settings). Al crearla,
    busca cada campo como variable de entorno (sin importar mayúsculas:
    `llm_modelo` ↔ `LLM_MODELO`) y, si no la encuentra, en el archivo `.env`.
    Si tampoco está, usa el valor por defecto. Después valida el tipo: si
    `FECHA_EJECUCION=hola`, falla con un mensaje claro en lugar de seguir con un dato malo.

Regla del proyecto:
    El resto del código pide la configuración con `cargar_configuracion()` y nunca
    lee `os.environ` directamente. Así hay un único lugar donde mirar.
"""

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Raíz del proyecto, calculada desde la ubicación de este archivo:
#   .../Agente_registro_Proveedor/src/registro_proveedor/config.py
#   parents[0] = registro_proveedor · parents[1] = src · parents[2] = raíz
# Así las rutas (datos/, out/, .env) funcionan sin importar desde qué carpeta
# se ejecute el programa.
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]


class Configuracion(BaseSettings):
    """Variables de entorno del proyecto. La lista documentada está en `.env.example`."""

    model_config = SettingsConfigDict(
        # Archivo del que se leen las variables si no están en el entorno.
        env_file=RAIZ_PROYECTO / ".env",
        env_file_encoding="utf-8",
        # Si el .env trae variables que no son de este proyecto, se ignoran en vez de fallar.
        extra="ignore",
        # Una variable vacía (como `FECHA_EJECUCION=` en .env.example) se trata como
        # si no existiera, en lugar de fallar al convertir "" en fecha.
        env_ignore_empty=True,
    )

    # Clave de Anthropic. Es opcional: el núcleo funciona sin ella (scripts/demo.py
    # no la usa). `SecretStr` guarda el texto, pero al imprimirlo muestra
    # `**********`, así que no se filtra por accidente en un log o en un print.
    # Para leer el valor real hay que pedirlo a propósito: `.get_secret_value()`.
    anthropic_api_key: SecretStr | None = None

    # Modelo de lenguaje. Por defecto uno económico. `min_length=1` evita que quede vacío.
    llm_modelo: str = Field(default="claude-haiku-5-5", min_length=1)

    # Esfuerzo del modelo (CA6, ajustada en el Paso 10): cuánto razona antes de responder.
    # Reemplaza a `temperature`, que el modelo ya no acepta. "medium" es el valor por
    # defecto de claude-haiku-5-5; "low" es más barato y más rápido (se mide en el Paso 17).
    llm_esfuerzo: Literal["low", "medium", "high", "xhigh", "max"] = "medium"

    # Cuánto esperar una respuesta (segundos) y cuántas veces reintentar si el problema
    # es pasajero (servicio saturado, caída momentánea). El SDK espera cada vez un poco más.
    llm_timeout_s: float = Field(default=30.0, gt=0, le=600)
    llm_reintentos: int = Field(default=3, ge=0, le=10)

    # Máximo de tokens que puede escribir el modelo en una respuesta. Si se queda corto,
    # la respuesta se corta a la mitad; 8000 sobra para un resumen y varias herramientas.
    # Paso 18: bajó de 8000 a 4000. Un resumen completo usa menos de 1500; un tope más
    # bajo hace que usar el chat para otra cosa (textos largos) rinda poco y cueste poco.
    llm_max_tokens: int = Field(default=4000, ge=256, le=64000)

    # Topes del ciclo del agente (CA1, Paso 12):
    # - cuántas veces se puede consultar al modelo en UN turno (un mensaje de la
    #   analista). Un caso completo usa unas 6; el tope evita un bucle sin fin.
    # - cuántos tokens puede gastar una conversación entera: entrada, salida y lo
    #   guardado en la caché. NO cuenta lo leído de la caché, que cuesta una décima
    #   parte (D46). 300 000 tokens cuestan, como mucho, unos USD 0.05 a 0.15.
    llm_max_iteraciones: int = Field(default=15, ge=1, le=50)
    llm_tope_tokens_sesion: int = Field(default=300_000, ge=1_000)
    # Paso 18 · cuántos mensajes puede escribir la analista en UNA conversación. Un caso
    # completo, con confirmación y envío, usa unos 5; 30 sobra para trabajar y corta el
    # uso del chat como asistente general.
    llm_max_mensajes_sesion: int = Field(default=30, ge=1, le=500)

    # Paso 18 · Topes de la demo ABIERTA (sin clave de acceso, decisión de Anderson, D65).
    # Por visitante (dirección IP), en memoria:
    tope_conversaciones_hora_ip: int = Field(default=5, ge=1)
    tope_mensajes_minuto_ip: int = Field(default=10, ge=1)
    # Para todos los visitantes juntos, por día (se guarda en out/uso-diario.json, así
    # que un reinicio no lo pone en cero):
    tope_conversaciones_dia: int = Field(default=100, ge=1)
    tope_usd_dia: float = Field(default=2.0, gt=0)

    # Paso 19 · En la demo publicada, cada conversación escribe en `out/sesiones/<id>/`,
    # para que dos visitantes que preparan el mismo caso no se pisen los archivos. En
    # local se deja apagado: todo queda en `out/<caso>/`, como siempre.
    salida_por_conversacion: bool = False

    # RN7: fecha de ejecución inyectable. Las vigencias de los soportes se comparan
    # con esta fecha. Si se fija (por ejemplo, en pruebas), el resultado no depende
    # del día en que se ejecuta. Si está vacía, se usa la fecha de hoy.
    fecha_ejecucion: date | None = None

    # `Literal` limita los valores posibles: cualquier otro texto es un error.
    nivel_log: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    def hay_clave_llm(self) -> bool:
        """Indica si hay una clave de Anthropic configurada, sin revelar cuál es."""
        return (
            self.anthropic_api_key is not None and self.anthropic_api_key.get_secret_value() != ""
        )

    def fecha_efectiva(self) -> date:
        """Devuelve la fecha inyectada o, si no hay, la de hoy."""
        return self.fecha_ejecucion or date.today()


def cargar_configuracion() -> Configuracion:
    """Lee la configuración desde el entorno y `.env`. Es la única forma de obtenerla."""
    return Configuracion()
