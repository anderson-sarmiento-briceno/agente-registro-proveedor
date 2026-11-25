"""Chat con el agente en la terminal, con el modelo real.

Uso:
    uv run python scripts/chat.py

Necesita la clave de Anthropic en `.env` (ANTHROPIC_API_KEY). Gasta poco dinero: un
caso completo cuesta del orden de un centavo de dólar. Después de cada respuesta
muestra qué herramientas pidió el modelo y en qué orden. Escriba «salir» para terminar.
Nunca imprime la clave.

La lógica está en `registro_proveedor.agente.chat_terminal`.
"""

import io
import sys

from registro_proveedor.agente.chat_terminal import conversar
from registro_proveedor.config import cargar_configuracion
from registro_proveedor.observabilidad import configurar_logs

if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if isinstance(sys.stdin, io.TextIOWrapper):
        sys.stdin.reconfigure(encoding="utf-8")
    # Solo avisos y errores en la terminal (van a stderr, en JSON): las líneas de cada
    # consulta al modelo ensuciarían la conversación. Con NIVEL_LOG=DEBUG se ven todas.
    config = cargar_configuracion()
    configurar_logs("WARNING" if config.nivel_log == "INFO" else config.nivel_log)
    sys.exit(conversar(config))
