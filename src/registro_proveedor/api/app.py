"""La app que levanta uvicorn, con la configuración de `.env`:

    uv run uvicorn registro_proveedor.api.app:app --reload

Solo eso: la API está en `aplicacion.py`. Así, las pruebas importan `crear_app` sin
que se arme la app real (que leería `.env` y configuraría los logs).
"""

from registro_proveedor.api.aplicacion import crear_app
from registro_proveedor.config import cargar_configuracion
from registro_proveedor.observabilidad import configurar_logs, obtener_logger

_config = cargar_configuracion()
configurar_logs(_config.nivel_log)
app = crear_app(_config)
obtener_logger().info(
    "api_lista", modelo=_config.llm_modelo, modelo_configurado=_config.hay_clave_llm()
)
