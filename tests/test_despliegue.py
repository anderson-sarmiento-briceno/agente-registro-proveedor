"""Pruebas de los archivos de despliegue (Paso 19): Dockerfile, .dockerignore, compose y Render.

No construyen la imagen (eso lo hace Docker, y tarda): revisan que los archivos digan lo
que deben. Un error aquí (por ejemplo, que .env entre a la imagen) sería grave y fácil de
cometer al editar, por eso queda vigilado en el CI.
"""

from pathlib import Path

import yaml

from registro_proveedor.config import RAIZ_PROYECTO, Configuracion

DOCKERFILE = (RAIZ_PROYECTO / "Dockerfile").read_text(encoding="utf-8")
DOCKERIGNORE = (RAIZ_PROYECTO / ".dockerignore").read_text(encoding="utf-8").splitlines()
COMPOSE = yaml.safe_load((RAIZ_PROYECTO / "docker-compose.yml").read_text(encoding="utf-8"))
RENDER = yaml.safe_load((RAIZ_PROYECTO / "render.yaml").read_text(encoding="utf-8"))


def _variables_de_render() -> dict[str, dict[str, object]]:
    (servicio,) = RENDER["services"]
    return {v["key"]: v for v in servicio["envVars"]}


def test_la_imagen_nunca_lleva_secretos_ni_lo_generado() -> None:
    for patron in (".env", "**/.env", "out/"):
        assert patron in DOCKERIGNORE, patron
    # Ni la clave escrita en el Dockerfile.
    assert "ANTHROPIC_API_KEY" not in DOCKERFILE


def test_la_imagen_lleva_lo_que_el_servidor_lee() -> None:
    """Si falta una de estas carpetas, el servidor no arranca (o el chat queda sin página)."""
    for carpeta in ("src/", "agente/", "knowledge/", "config/", "datos/", "web/"):
        assert f"COPY {carpeta} {carpeta}" in DOCKERFILE, carpeta
        assert carpeta not in DOCKERIGNORE
    # "*.html" solo excluye la raíz: web/index.html sí entra.
    assert "**/*.html" not in DOCKERIGNORE


def test_corre_sin_privilegios_con_health_check_y_un_solo_proceso() -> None:
    assert "USER agente" in DOCKERFILE
    assert "HEALTHCHECK" in DOCKERFILE and "/api/health" in DOCKERFILE
    assert "uv sync --locked --no-dev" in DOCKERFILE  # las versiones exactas de uv.lock
    assert "--proxy-headers" in DOCKERFILE  # la IP real detrás del proxy de Render
    assert "--workers" not in DOCKERFILE  # las conversaciones viven en UN proceso


def test_render_plan_gratuito_y_la_clave_como_secreto() -> None:
    (servicio,) = RENDER["services"]
    assert servicio["plan"] == "free"
    assert servicio["runtime"] == "docker"
    assert servicio["healthCheckPath"] == "/api/health"
    variables = _variables_de_render()
    # La clave no lleva valor: Render la pide en su panel y la guarda como secreto.
    assert variables["ANTHROPIC_API_KEY"] == {"key": "ANTHROPIC_API_KEY", "sync": False}


def test_render_y_compose_usan_variables_que_existen() -> None:
    """Una variable mal escrita se ignoraría en silencio (`extra="ignore"`)."""
    conocidas = {nombre.upper() for nombre in Configuracion.model_fields}
    assert set(_variables_de_render()) <= conocidas
    (servicio,) = COMPOSE["services"].values()
    assert set(servicio["environment"]) <= conocidas


def test_render_y_compose_dicen_lo_mismo() -> None:
    (servicio,) = COMPOSE["services"].values()
    render = _variables_de_render()
    for clave, valor in servicio["environment"].items():
        assert render[clave]["value"] == valor, clave


def test_la_configuracion_de_la_demo_es_valida(tmp_path: Path) -> None:
    variables = {k: str(v["value"]) for k, v in _variables_de_render().items() if "value" in v}
    config = Configuracion.model_validate({k.lower(): v for k, v in variables.items()})
    assert config.salida_por_conversacion is True
    assert config.fecha_ejecucion is not None
