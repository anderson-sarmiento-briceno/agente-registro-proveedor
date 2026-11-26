"""Pruebas de contrato de la API (Paso 15). Sin red: modelo falso y `out/` temporal.

`TestClient` (de FastAPI) llama a la app como lo haría un navegador, pero sin abrir un
puerto: cada `cliente.post(...)` recorre la ruta, la validación y la respuesta reales.

Cómo está organizado:
    1. /api/health: dice si hay modelo, nunca la clave.
    2. /api/chat: sesión nueva, el caso completo con tool_calls EN ORDEN, la sesión sigue.
    3. /api/confirmations: pedir → pendiente → aprobar / rechazar; ids ajenos o inventados.
    4. /api/sessions: el historial tal como lo vio la analista.
    5. Errores claros en español: 404, 409, 422, 503.
    6. Seguridad: ninguna respuesta lleva la clave ni la cuenta completa.
    7. OpenAPI: las 4 rutas documentadas.
"""

import dataclasses
import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from registro_proveedor.agente.ciclo import Sesion
from registro_proveedor.agente.llm.adaptador import RespuestaModelo
from registro_proveedor.agente.llm.falso import AdaptadorFalso, pide, responde
from registro_proveedor.api.aplicacion import crear_app
from registro_proveedor.api.sesiones import AlmacenDeSesiones
from registro_proveedor.config import Configuracion
from registro_proveedor.herramientas.base import Contexto
from tests.ayudas import DATOS_REALES

CO = "co-industrias-delta"
EC = "ec-corp-andina"
CLAVE = "sk-ant-clave-de-prueba-que-no-debe-aparecer"

ORDEN_DEL_FLUJO = [
    "proveedor_leer_solicitud",
    "proveedor_mapear_campos",
    "proveedor_generar_formulario",
    "proveedor_armar_paquete",
]


def _config(clave: str | None = CLAVE) -> Configuracion:
    return Configuracion(anthropic_api_key=SecretStr(clave) if clave else None)


def _cliente(contexto: Contexto, *guion: RespuestaModelo, **opciones: object) -> TestClient:
    """La API con el modelo falso, sobre los datos reales y un `out/` temporal."""

    def crear_contexto(sesion_id: str) -> Contexto:
        return dataclasses.replace(contexto, sesion_id=sesion_id)

    app = crear_app(
        _config(),
        adaptador=AdaptadorFalso(list(guion)),
        crear_contexto=crear_contexto,
        **opciones,  # type: ignore[arg-type]
    )
    return TestClient(app)


def _caso_completo(caso: str = CO) -> list[RespuestaModelo]:
    return [
        *(pide(nombre, {"caso": caso}) for nombre in ORDEN_DEL_FLUJO),
        responde(f"**Caso:** {caso} · listo para firma. ¿Revisamos otro caso?"),
    ]


def _confirmar_ruc() -> list[RespuestaModelo]:
    return [
        pide("proveedor_mapear_campos", {"caso": EC}),
        pide("proveedor_confirmar_campo", {"caso": EC, "etiqueta": "RUC", "decision": "aceptar"}),
        responde("Pulse Aprobar para aceptar el NIT como RUC."),
    ]


def _json(respuesta: object) -> dict[str, object]:
    assert hasattr(respuesta, "json")
    datos = respuesta.json()
    assert isinstance(datos, dict)
    return datos


# ---------- 1. /api/health ----------


def test_health_con_modelo(contexto: Contexto) -> None:
    r = _cliente(contexto).get("/api/health")
    assert r.status_code == 200
    assert r.json() == {
        "ok": True,
        "provider": "anthropic",
        "model": "modelo-falso",
        "llm_configured": True,
        "prompt_version": "7",
    }


def test_health_sin_clave_no_falla(contexto: Contexto) -> None:
    """Sin clave el servidor arranca igual y lo dice; el chat responde 503."""
    app = crear_app(_config(clave=None))
    cliente = TestClient(app)
    salud = cliente.get("/api/health").json()
    assert salud["llm_configured"] is False
    r = cliente.post("/api/chat", json={"message": "hola"})
    assert r.status_code == 503
    assert "falta ANTHROPIC_API_KEY" in r.json()["detail"]


# ---------- 2. /api/chat ----------


def test_chat_crea_una_sesion_y_lista_las_herramientas_en_orden(contexto: Contexto) -> None:
    r = _cliente(contexto, *_caso_completo()).post(
        "/api/chat", json={"message": "Prepara el caso de Colombia"}
    )
    assert r.status_code == 200
    datos = _json(r)
    assert re.fullmatch(r"[0-9a-f]{32}", str(datos["session_id"]))
    assert datos["reply"] == f"**Caso:** {CO} · listo para firma. ¿Revisamos otro caso?"
    assert datos["finish_reason"] == "answered"
    llamadas = datos["tool_calls"]
    assert isinstance(llamadas, list)
    assert [ll["name"] for ll in llamadas] == ORDEN_DEL_FLUJO
    assert [ll["order"] for ll in llamadas] == [1, 2, 3, 4]
    assert llamadas[0] == {
        "order": 1,
        "name": "proveedor_leer_solicitud",
        "arguments": {"caso": CO},
        "status": "executed",
        "ok": True,
        "summary": "CO · xlsx · 17 campos · 4 soportes exigidos",
    }
    assert llamadas[-1]["summary"] == f"out/{CO}/paquete · listo para firma"
    assert datos["needs_confirmation"] is False
    assert datos["confirmation_id"] is None
    assert (contexto.salida / CO / "paquete" / "checklist.md").is_file()


def test_chat_sigue_en_la_misma_sesion(contexto: Contexto) -> None:
    cliente = _cliente(contexto, responde("Hola, ¿qué caso?"), responde("Con gusto."))
    primera = _json(cliente.post("/api/chat", json={"message": "hola"}))
    segunda = _json(
        cliente.post("/api/chat", json={"session_id": primera["session_id"], "message": "gracias"})
    )
    assert segunda["session_id"] == primera["session_id"]
    assert segunda["reply"] == "Con gusto."


def test_cada_sesion_tiene_su_historial(contexto: Contexto) -> None:
    cliente = _cliente(contexto, responde("uno"), responde("dos"))
    a = _json(cliente.post("/api/chat", json={"message": "a"}))
    b = _json(cliente.post("/api/chat", json={"message": "b"}))
    assert a["session_id"] != b["session_id"]
    turnos_a = _json(cliente.get(f"/api/sessions/{a['session_id']}"))["turns"]
    assert isinstance(turnos_a, list)
    assert [t["input"] for t in turnos_a] == ["a"]


# ---------- 3. /api/confirmations ----------


def test_confirmacion_pendiente_y_aprobada(contexto: Contexto) -> None:
    cliente = _cliente(
        contexto,
        *_confirmar_ruc(),
        pide("proveedor_armar_paquete", {"caso": EC}),
        responde("Listo: el RUC quedó confirmado."),
    )
    pedido = _json(cliente.post("/api/chat", json={"message": "Mapea Ecuador; acepto el RUC"}))
    assert pedido["needs_confirmation"] is True
    confirmacion = pedido["confirmation_id"]
    assert isinstance(confirmacion, str)
    assert pedido["confirmations"] == [
        {
            "id": confirmacion,
            "tool": "proveedor_confirmar_campo",
            "description": (
                f"proveedor_confirmar_campo: caso {EC} · etiqueta RUC · decision aceptar"
            ),
        }
    ]
    llamadas = pedido["tool_calls"]
    assert isinstance(llamadas, list)
    assert llamadas[1]["status"] == "pending"

    aprobada = cliente.post(
        f"/api/confirmations/{confirmacion}",
        json={"session_id": pedido["session_id"], "approve": True},
    )
    assert aprobada.status_code == 200
    datos = _json(aprobada)
    llamadas = datos["tool_calls"]
    assert isinstance(llamadas, list)
    assert [(ll["name"], ll["status"]) for ll in llamadas] == [
        ("proveedor_confirmar_campo", "approved"),
        ("proveedor_armar_paquete", "executed"),
    ]
    assert datos["needs_confirmation"] is False
    mapeo = json.loads((contexto.salida / EC / "mapeo.json").read_text(encoding="utf-8"))
    ruc = next(c for c in mapeo["campos"] if c["etiqueta"] == "RUC")
    assert ruc["estado"] == "lleno"


def test_confirmacion_rechazada(contexto: Contexto) -> None:
    cliente = _cliente(contexto, *_confirmar_ruc(), responde("Entendido."))
    pedido = _json(cliente.post("/api/chat", json={"message": "Mapea Ecuador; acepto el RUC"}))
    datos = _json(
        cliente.post(
            f"/api/confirmations/{pedido['confirmation_id']}",
            json={"session_id": pedido["session_id"], "approve": False},
        )
    )
    llamadas = datos["tool_calls"]
    assert isinstance(llamadas, list)
    assert llamadas[0]["status"] == "rejected"


def test_no_se_aprueba_la_confirmacion_de_otra_sesion(contexto: Contexto) -> None:
    cliente = _cliente(contexto, *_confirmar_ruc(), responde("Hola."))
    pedido = _json(cliente.post("/api/chat", json={"message": "Mapea Ecuador; acepto el RUC"}))
    otra = _json(cliente.post("/api/chat", json={"message": "hola"}))
    r = cliente.post(
        f"/api/confirmations/{pedido['confirmation_id']}",
        json={"session_id": otra["session_id"], "approve": True},
    )
    assert r.status_code == 409
    assert "No se ejecutó nada" in r.json()["detail"]
    mapeo = json.loads((contexto.salida / EC / "mapeo.json").read_text(encoding="utf-8"))
    assert next(c for c in mapeo["campos"] if c["etiqueta"] == "RUC")["confirmacion"] is None


def test_no_se_aprueba_dos_veces(contexto: Contexto) -> None:
    cliente = _cliente(contexto, *_confirmar_ruc(), responde("Listo."))
    pedido = _json(cliente.post("/api/chat", json={"message": "Mapea Ecuador; acepto el RUC"}))
    cuerpo = {"session_id": pedido["session_id"], "approve": True}
    url = f"/api/confirmations/{pedido['confirmation_id']}"
    assert cliente.post(url, json=cuerpo).status_code == 200
    assert cliente.post(url, json=cuerpo).status_code == 409


def test_un_mensaje_nuevo_cancela_la_pendiente(contexto: Contexto) -> None:
    cliente = _cliente(contexto, *_confirmar_ruc(), responde("De acuerdo."))
    pedido = _json(cliente.post("/api/chat", json={"message": "Mapea Ecuador; acepto el RUC"}))
    siguiente = _json(
        cliente.post(
            "/api/chat", json={"session_id": pedido["session_id"], "message": "No, espera"}
        )
    )
    canceladas = siguiente["cancelled"]
    assert isinstance(canceladas, list)
    assert [c["id"] for c in canceladas] == [pedido["confirmation_id"]]


# ---------- 4. /api/sessions ----------


def test_historial_tal_como_lo_vio_la_analista(contexto: Contexto) -> None:
    cliente = _cliente(contexto, *_confirmar_ruc(), responde("Listo."))
    pedido = _json(cliente.post("/api/chat", json={"message": "Mapea Ecuador; acepto el RUC"}))
    sesion = str(pedido["session_id"])
    cliente.post(
        f"/api/confirmations/{pedido['confirmation_id']}",
        json={"session_id": sesion, "approve": True},
    )
    historial = _json(cliente.get(f"/api/sessions/{sesion}"))
    turnos = historial["turns"]
    assert isinstance(turnos, list)
    assert [(t["kind"], t["input"]) for t in turnos] == [
        ("message", "Mapea Ecuador; acepto el RUC"),
        ("approve", pedido["confirmation_id"]),
    ]
    assert turnos[0]["response"] == pedido  # la misma respuesta que recibió la analista
    assert historial["pending"] == []


# ---------- 5. Errores claros ----------


def test_sesion_inexistente(contexto: Contexto) -> None:
    cliente = _cliente(contexto)
    inventada = "0" * 32
    r = cliente.post("/api/chat", json={"session_id": inventada, "message": "hola"})
    assert r.status_code == 404
    assert "No existe esa conversación" in r.json()["detail"]
    assert cliente.get(f"/api/sessions/{inventada}").status_code == 404


def test_la_sesion_vence_por_inactividad(contexto: Contexto) -> None:
    ahora = [datetime(2026, 9, 1, 12, 0, tzinfo=UTC)]

    def crear(sesion_id: str) -> Sesion:
        return Sesion(dataclasses.replace(contexto, sesion_id=sesion_id))

    almacen = AlmacenDeSesiones(crear, reloj=lambda: ahora[0])
    cliente = _cliente(contexto, responde("Hola."), almacen=almacen)
    sesion = _json(cliente.post("/api/chat", json={"message": "hola"}))["session_id"]
    ahora[0] += timedelta(hours=3)
    assert cliente.get(f"/api/sessions/{sesion}").status_code == 404


def test_demasiadas_sesiones(contexto: Contexto) -> None:
    def crear(sesion_id: str) -> Sesion:
        return Sesion(dataclasses.replace(contexto, sesion_id=sesion_id))

    almacen = AlmacenDeSesiones(crear, maximo=1)
    cliente = _cliente(contexto, responde("uno"), almacen=almacen)
    assert cliente.post("/api/chat", json={"message": "a"}).status_code == 200
    r = cliente.post("/api/chat", json={"message": "b"})
    assert r.status_code == 503
    assert "demasiadas conversaciones" in r.json()["detail"]


@pytest.mark.parametrize(
    ("cuerpo", "pista"),
    [
        ({"message": ""}, "«message»"),
        ({"message": "   "}, "el mensaje está vacío"),
        ({"message": "x" * 4001}, "«message»"),
        ({"message": "hola", "enviar": True}, "«enviar»"),  # campo desconocido
        ({"session_id": "../otra", "message": "hola"}, "«session_id»"),
        ({}, "«message»"),
    ],
)
def test_solicitud_no_valida_en_espanol(
    contexto: Contexto, cuerpo: dict[str, object], pista: str
) -> None:
    r = _cliente(contexto).post("/api/chat", json=cuerpo)
    assert r.status_code == 422
    detalle = r.json()["detail"]
    assert detalle.startswith("solicitud no válida: ")
    assert pista in detalle
    assert "x" * 100 not in detalle  # no devuelve lo que se envió


def test_id_de_confirmacion_mal_formado(contexto: Contexto) -> None:
    r = _cliente(contexto).post(
        "/api/confirmations/../../x", json={"session_id": "0" * 32, "approve": True}
    )
    # 404/422 si lo atiende la API; 405 si cae en los archivos del front (Paso 16).
    # En ningún caso se ejecuta nada.
    assert r.status_code in (404, 405, 422)


# ---------- 6. Seguridad: ni la clave ni datos completos ----------


def test_ninguna_respuesta_expone_la_clave_ni_la_cuenta(contexto: Contexto) -> None:
    maestro = json.loads((DATOS_REALES / "repositorio" / "maestro.json").read_text("utf-8"))
    cuenta = maestro["banco"]["numero_cuenta"]
    cliente = _cliente(
        contexto,
        *_caso_completo(),
        responde(f"La cuenta es {cuenta}."),  # el modelo "inventa" la cuenta completa
    )
    respuestas: list[str] = []
    chat = cliente.post("/api/chat", json={"message": "Prepara el caso de Colombia"})
    respuestas.append(chat.text)
    sesion = chat.json()["session_id"]
    respuestas.append(
        cliente.post("/api/chat", json={"session_id": sesion, "message": "¿y la cuenta?"}).text
    )
    respuestas.append(cliente.get(f"/api/sessions/{sesion}").text)
    respuestas.append(cliente.get("/api/health").text)
    respuestas.append(cliente.get("/openapi.json").text)
    for texto in respuestas:
        assert CLAVE not in texto
        assert cuenta not in texto
    # La respuesta "inventada" llegó con el dato oculto.
    segunda = json.loads(respuestas[1])
    assert "[dato no verificado]" in segunda["reply"]
    assert segunda["hidden_values"] == 1


# ---------- 7. OpenAPI ----------


def test_openapi_documenta_las_4_rutas(contexto: Contexto) -> None:
    esquema = _cliente(contexto).get("/openapi.json").json()
    rutas = esquema["paths"]
    assert set(rutas) == {
        "/api/chat",
        "/api/confirmations/{confirmation_id}",
        "/api/sessions/{session_id}",
        "/api/health",
    }
    assert "ChatResponse" in esquema["components"]["schemas"]
    assert _cliente(contexto).get("/docs").status_code == 200
