"""Pruebas del front de chat (Paso 16), desde el lado del servidor.

El comportamiento de la página (botones, tabla, "pensando…") se prueba a mano en el
navegador. Aquí se comprueba lo que se puede comprobar sin abrir uno:
    - que FastAPI sirve la página y sus archivos, y que la API sigue funcionando;
    - que cada respuesta lleva los encabezados de seguridad (CSP);
    - que la página no tiene scripts en línea y que `app.js` nunca usa `innerHTML`
      (así un `<script>` en una respuesta del modelo no se puede ejecutar);
    - que `app.js` llama a las rutas que existen y usa los campos del contrato.
"""

import dataclasses
import re

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from registro_proveedor.agente.llm.falso import AdaptadorFalso, responde
from registro_proveedor.api.aplicacion import CARPETA_WEB, CSP, crear_app
from registro_proveedor.api.esquemas import ChatResponse, PortalField, PortalValuesResponse
from registro_proveedor.config import Configuracion
from registro_proveedor.herramientas.base import Contexto

APP_JS = (CARPETA_WEB / "app.js").read_text(encoding="utf-8")
INDEX = (CARPETA_WEB / "index.html").read_text(encoding="utf-8")
# El código de app.js SIN sus comentarios (los comentarios sí mencionan `innerHTML`,
# justamente para explicar por qué no se usa).
CODIGO_JS = re.sub(
    r"^\s*//.*$", "", re.sub(r"/\*.*?\*/", "", APP_JS, flags=re.DOTALL), flags=re.MULTILINE
)


@pytest.fixture
def cliente(contexto: Contexto) -> TestClient:
    app = crear_app(
        Configuracion(anthropic_api_key=SecretStr("sk-ant-de-prueba")),
        adaptador=AdaptadorFalso([responde("<script>alert(1)</script> **hola**")]),
        crear_contexto=lambda sesion_id: dataclasses.replace(contexto, sesion_id=sesion_id),
    )
    return TestClient(app)


# ---------- La página y sus archivos ----------


@pytest.mark.parametrize(
    ("ruta", "tipo"),
    [
        ("/", "text/html"),
        ("/index.html", "text/html"),
        ("/app.js", "javascript"),
        ("/estilos.css", "text/css"),
        ("/icono.svg", "image/svg+xml"),
    ],
)
def test_sirve_la_pagina_y_sus_archivos(cliente: TestClient, ruta: str, tipo: str) -> None:
    r = cliente.get(ruta)
    assert r.status_code == 200
    assert tipo in r.headers["content-type"]


def test_la_api_sigue_respondiendo_con_la_pagina_montada(cliente: TestClient) -> None:
    assert cliente.get("/api/health").json()["ok"] is True
    assert cliente.post("/api/chat", json={"message": "hola"}).status_code == 200
    assert cliente.get("/no-existe.txt").status_code == 404


def test_fuera_de_la_carpeta_web_no_se_sirve_nada(cliente: TestClient) -> None:
    for ruta in ("/../.env", "/%2e%2e/.env", "/..%2f.env", "/../datos/repositorio/maestro.json"):
        r = cliente.get(ruta)
        assert r.status_code == 404, ruta
        assert "ANTHROPIC" not in r.text


# ---------- Encabezados de seguridad ----------


@pytest.mark.parametrize("ruta", ["/", "/app.js", "/api/health"])
def test_encabezados_de_seguridad(cliente: TestClient, ruta: str) -> None:
    r = cliente.get(ruta)
    assert r.headers["Content-Security-Policy"] == CSP
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "no-referrer"


def test_la_csp_no_permite_scripts_de_afuera_ni_en_linea() -> None:
    assert "script-src 'self'" in CSP
    assert "unsafe-inline" not in CSP
    assert "unsafe-eval" not in CSP
    assert "frame-ancestors 'none'" in CSP


def test_docs_sigue_funcionando_sin_csp(cliente: TestClient) -> None:
    r = cliente.get("/docs")
    assert r.status_code == 200
    assert "Content-Security-Policy" not in r.headers


# ---------- La página no puede ejecutar lo que dice el modelo ----------


def test_index_sin_scripts_en_linea() -> None:
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", INDEX, flags=re.DOTALL)
    assert scripts == [""]  # solo `<script src="/app.js">`, vacío por dentro
    assert 'src="/app.js"' in INDEX
    assert not re.search(r"\son[a-z]+\s*=", INDEX)  # nada de onclick="…"


def test_app_js_nunca_usa_html_crudo() -> None:
    for peligroso in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert peligroso not in CODIGO_JS, peligroso
    assert "textContent" in CODIGO_JS  # el texto se agrega como texto


def test_la_respuesta_con_html_llega_como_texto(cliente: TestClient) -> None:
    """La API devuelve el texto tal cual; es la página la que lo muestra como texto."""
    r = cliente.post("/api/chat", json={"message": "hola"}).json()
    assert r["reply"].startswith("<script>alert(1)</script>")
    assert r.get("html") is None  # la API nunca manda HTML armado


# ---------- app.js usa el contrato real ----------


def test_app_js_usa_las_rutas_de_la_api() -> None:
    for ruta in ("/api/chat", "/api/confirmations/", "/api/sessions/", "/api/health"):
        assert ruta in APP_JS


def test_app_js_usa_los_campos_del_contrato() -> None:
    usados = set(re.findall(r"\br\.([a-z_]+)", APP_JS))
    assert usados, "app.js debería leer campos de la respuesta (r.reply, r.tool_calls…)"
    assert usados <= set(ChatResponse.model_fields), usados - set(ChatResponse.model_fields)
    for campo in ("reply", "tool_calls", "confirmations", "cancelled", "alerts", "session_id"):
        assert campo in usados


def test_app_js_usa_el_contrato_de_los_valores_del_portal() -> None:
    """Paso 18: la tarjeta del portal lee solo campos que existen en la respuesta."""
    assert "/portal-values?session_id=" in APP_JS
    usados = set(re.findall(r"\bvalores\.([a-z_]+)", APP_JS))
    assert usados == {"client", "fields", "note"} <= set(PortalValuesResponse.model_fields)
    de_campo = set(re.findall(r"\bcampo\.([a-z_]+)", APP_JS))
    assert de_campo <= set(PortalField.model_fields), de_campo
    assert "campo.masked" in APP_JS  # lo enmascarado no se puede copiar


def test_app_js_descarga_el_paquete_y_no_copia_respuestas() -> None:
    """Paso 19: el .zip se baja con un enlace; "Copiar respuesta" se quitó (Anderson)."""
    assert "/package.zip?session_id=" in APP_JS
    assert "Copiar respuesta" not in APP_JS


def test_app_js_conoce_todos_los_estados_de_una_herramienta() -> None:
    for estado in ("executed", "failed", "pending", "approved", "rejected"):
        assert f"{estado}:" in APP_JS
