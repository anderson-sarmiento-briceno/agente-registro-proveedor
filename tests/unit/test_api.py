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
import io
import json
import re
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from registro_proveedor.agente.ciclo import Sesion
from registro_proveedor.agente.llm.adaptador import RespuestaModelo, Uso
from registro_proveedor.agente.llm.falso import AdaptadorFalso, pide, responde
from registro_proveedor.api.aplicacion import contexto_de_conversacion, crear_app
from registro_proveedor.api.limites import LimitadorPorVisitante, UsoDiario
from registro_proveedor.api.sesiones import AlmacenDeSesiones
from registro_proveedor.config import Configuracion
from registro_proveedor.dominio.descarga import zip_del_paquete
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

    # Paso 18 · El conteo diario va al `out/` temporal, nunca al `out/` real.
    opciones.setdefault(
        "uso_diario", UsoDiario(contexto.salida, tope_conversaciones=100, tope_usd=2.0)
    )
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
        "prompt_version": "8",
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


def test_openapi_documenta_las_6_rutas(contexto: Contexto) -> None:
    esquema = _cliente(contexto).get("/openapi.json").json()
    rutas = esquema["paths"]
    assert set(rutas) == {
        "/api/chat",
        "/api/confirmations/{confirmation_id}",
        "/api/sessions/{session_id}",
        "/api/cases/{case_id}/portal-values",  # Paso 18 (D57)
        "/api/cases/{case_id}/package.zip",  # Paso 19
        "/api/health",
    }
    assert "ChatResponse" in esquema["components"]["schemas"]
    assert _cliente(contexto).get("/docs").status_code == 200


# ---------- 8. Paso 18 · Topes de la demo abierta ----------


def test_tope_de_mensajes_por_minuto_del_visitante(contexto: Contexto) -> None:
    limitador = LimitadorPorVisitante(conversaciones_por_hora=10, mensajes_por_minuto=2)
    cliente = _cliente(contexto, responde("Uno."), responde("Dos."), limitador=limitador)
    sesion = cliente.post("/api/chat", json={"message": "hola"}).json()["session_id"]
    assert cliente.post("/api/chat", json={"session_id": sesion, "message": "a"}).is_success
    tercero = cliente.post("/api/chat", json={"session_id": sesion, "message": "b"})
    assert tercero.status_code == 429
    assert tercero.json()["detail"].startswith("Va muy rápido")


def test_tope_de_conversaciones_por_hora_del_visitante(contexto: Contexto) -> None:
    limitador = LimitadorPorVisitante(conversaciones_por_hora=1, mensajes_por_minuto=10)
    cliente = _cliente(contexto, responde("Hola."), limitador=limitador)
    assert cliente.post("/api/chat", json={"message": "hola"}).is_success
    otra = cliente.post("/api/chat", json={"message": "otra conversación"})
    assert otra.status_code == 429
    assert "muchas conversaciones" in otra.json()["detail"]


def test_tope_diario_de_conversaciones(contexto: Contexto) -> None:
    diario = UsoDiario(contexto.salida, tope_conversaciones=1, tope_usd=2.0)
    cliente = _cliente(contexto, responde("Hola."), uso_diario=diario)
    assert cliente.post("/api/chat", json={"message": "hola"}).is_success
    otra = cliente.post("/api/chat", json={"message": "hola"})
    assert otra.status_code == 429
    assert "límite de conversaciones por hoy" in otra.json()["detail"]
    assert (
        json.loads((contexto.salida / "uso-diario.json").read_text("utf-8"))["conversaciones"] == 1
    )


def test_el_costo_se_suma_al_tope_diario(contexto: Contexto) -> None:
    """Cuando el gasto del día llega al tope, ni siquiera una conversación abierta sigue."""
    caro = responde("Hola.").model_copy(update={"uso": Uso(entrada=1_000_000)})  # ≈ USD 5
    diario = UsoDiario(contexto.salida, tope_conversaciones=100, tope_usd=1.0)
    cliente = _cliente(contexto, caro, uso_diario=diario)
    sesion = cliente.post("/api/chat", json={"message": "hola"}).json()["session_id"]
    assert diario.hoy[1] > 1.0
    siguiente = cliente.post("/api/chat", json={"session_id": sesion, "message": "sigue"})
    assert siguiente.status_code == 429
    assert "límite de uso por hoy" in siguiente.json()["detail"]


def test_una_sesion_inexistente_da_404_antes_que_un_tope(contexto: Contexto) -> None:
    r = _cliente(contexto).post("/api/chat", json={"session_id": "0" * 32, "message": "hola"})
    assert r.status_code == 404


# ---------- 9. Paso 18 · Valores del portal para copiar (D57) ----------

PA = "pa-logistica-istmo"


def _portal_preparado(contexto: Contexto) -> tuple[TestClient, str]:
    cliente = _cliente(
        contexto,
        pide("proveedor_leer_solicitud", {"caso": PA}),
        pide("proveedor_mapear_campos", {"caso": PA}),
        responde("Listo."),
    )
    sesion = cliente.post("/api/chat", json={"message": "Prepara Panamá"}).json()["session_id"]
    return cliente, sesion


def test_valores_del_portal_con_lo_sensible_enmascarado(contexto: Contexto) -> None:
    cliente, sesion = _portal_preparado(contexto)
    r = cliente.get(f"/api/cases/{PA}/portal-values", params={"session_id": sesion})
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"
    campos = {c["label"]: c for c in r.json()["fields"]}
    # La cuenta completa NUNCA sale por la página pública (D65): solo los 4 últimos.
    maestro = json.loads((DATOS_REALES / "repositorio" / "maestro.json").read_text("utf-8"))
    cuenta = maestro["banco"]["numero_cuenta"]
    assert cuenta not in r.text
    assert campos["Número de cuenta"]["value"] == "****" + cuenta[-4:]
    assert campos["Número de cuenta"]["masked"] is True
    # Lo demás sí, para copiarlo; lo pendiente de confirmar queda sin valor.
    assert campos["Banco"]["value"] == maestro["banco"]["nombre"]
    assert campos["Banco"]["masked"] is False
    assert campos["RUC"]["value"] is None
    assert campos["RUC"]["status"] == "PENDIENTE de confirmación"
    assert "valores-portal.md" in r.json()["note"]
    # Queda en el log quién los vio, sin los valores.
    log = (contexto.salida / PA / "log.jsonl").read_text("utf-8")
    assert "vista_valores_portal" in log
    assert cuenta not in log


def test_valores_del_portal_errores(contexto: Contexto) -> None:
    cliente, sesion = _portal_preparado(contexto)

    def pedir(caso: str, sesion_id: str = sesion) -> tuple[int, str]:
        r = cliente.get(f"/api/cases/{caso}/portal-values", params={"session_id": sesion_id})
        return r.status_code, r.json()["detail"]

    assert pedir(CO) == (
        404,
        "Ese caso no se llena en un portal web: su formulario es un archivo (Excel o PDF).",
    )
    assert pedir("no-existe")[0] == 404
    assert pedir(PA, "0" * 32)[0] == 404  # sesión inexistente
    assert pedir("../datos")[0] in (404, 422)
    # Un caso de portal que todavía no se preparó en ESTA sesión.
    otro_contexto = dataclasses.replace(contexto, salida=contexto.salida.parent / "otro-out")
    otro, sesion_vacia = _cliente(otro_contexto, responde("Hola.")), ""
    sesion_vacia = otro.post("/api/chat", json={"message": "hola"}).json()["session_id"]
    r = otro.get(f"/api/cases/{PA}/portal-values", params={"session_id": sesion_vacia})
    assert r.status_code == 404
    assert "primero pídale al agente que lo prepare" in r.json()["detail"]


# ---------- 10. Paso 19 · Descargar el paquete (.zip) ----------


def test_descargar_el_paquete_sin_el_formulario(contexto: Contexto) -> None:
    cliente = _cliente(
        contexto,
        pide("proveedor_leer_solicitud", {"caso": PA}),
        pide("proveedor_mapear_campos", {"caso": PA}),
        pide("proveedor_armar_paquete", {"caso": PA}),
        responde("Listo."),
    )
    sesion = cliente.post("/api/chat", json={"message": "Prepara Panamá"}).json()["session_id"]
    r = cliente.get(f"/api/cases/{PA}/package.zip", params={"session_id": sesion})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert f'filename="paquete-{PA}.zip"' in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"

    with zipfile.ZipFile(io.BytesIO(r.content)) as zip_:
        nombres = set(zip_.namelist())
        contenido = b"".join(zip_.read(n) for n in nombres)
    assert {f"{PA}/checklist.md", f"{PA}/borrador-correo.md", f"{PA}/LEEME.txt"} <= nombres
    assert f"{PA}/manifiesto.json" in nombres
    # Los soportes exigidos por Panamá van en el zip.
    assert any(n.startswith(f"{PA}/rut") for n in nombres)
    # El formulario lleno NO (trae la cuenta completa), y la cuenta no aparece en nada.
    assert f"{PA}/valores-portal.md" not in nombres
    maestro = json.loads((DATOS_REALES / "repositorio" / "maestro.json").read_text("utf-8"))
    assert maestro["banco"]["numero_cuenta"].encode() not in contenido
    assert "descarga_paquete" in (contexto.salida / PA / "log.jsonl").read_text("utf-8")


def test_descargar_sin_paquete_o_caso_inexistente(contexto: Contexto) -> None:
    cliente = _cliente(contexto, responde("Hola."))
    sesion = cliente.post("/api/chat", json={"message": "hola"}).json()["session_id"]
    sin_paquete = cliente.get(f"/api/cases/{PA}/package.zip", params={"session_id": sesion})
    assert sin_paquete.status_code == 404
    assert "primero pídale al agente" in sin_paquete.json()["detail"]
    no_existe = cliente.get("/api/cases/no-existe/package.zip", params={"session_id": sesion})
    assert no_existe.status_code == 404
    otra_sesion = cliente.get(f"/api/cases/{PA}/package.zip", params={"session_id": "0" * 32})
    assert otra_sesion.status_code == 404


def test_el_zip_lleva_la_constancia_si_se_registro_el_envio(tmp_path: Path) -> None:
    carpeta = tmp_path / PA
    (carpeta / "paquete").mkdir(parents=True)
    (carpeta / "paquete" / "checklist.md").write_text("ok", encoding="utf-8")
    (carpeta / "paquete" / "formulario.xlsx").write_bytes(b"datos completos")
    (carpeta / "constancia-envio.md").write_text("constancia", encoding="utf-8")
    contenido = zip_del_paquete(carpeta)
    assert contenido is not None
    with zipfile.ZipFile(io.BytesIO(contenido)) as zip_:
        nombres = set(zip_.namelist())
        leeme = zip_.read(f"{PA}/LEEME.txt").decode("utf-8")
    assert nombres == {f"{PA}/checklist.md", f"{PA}/constancia-envio.md", f"{PA}/LEEME.txt"}
    assert "formulario.xlsx" in leeme  # explica qué se dejó fuera
    assert zip_del_paquete(tmp_path / "sin-paquete") is None


# ---------- 11. Paso 19 · Una carpeta por conversación ----------


def test_cada_conversacion_tiene_su_carpeta(tmp_path: Path) -> None:
    config = Configuracion(salida_por_conversacion=True)
    a = contexto_de_conversacion(config, "a" * 32, tmp_path / "out")
    b = contexto_de_conversacion(config, "b" * 32, tmp_path / "out")
    assert a.salida == tmp_path / "out" / "sesiones" / ("a" * 32)
    assert a.salida != b.salida
    # Ante el modelo y la analista, la ruta sigue diciendo "out/<caso>/…", sin el id.
    assert a.ruta_en_salida(PA, "paquete") == f"out/{PA}/paquete"


def test_en_local_todo_va_a_out(tmp_path: Path) -> None:
    contexto = contexto_de_conversacion(Configuracion(), "a" * 32, tmp_path / "out")
    assert contexto.salida == tmp_path / "out"


def test_dos_conversaciones_no_se_pisan(tmp_path: Path) -> None:
    """De punta a punta: dos visitantes preparan Panamá; cada uno tiene su paquete."""
    config = Configuracion(anthropic_api_key=SecretStr(CLAVE), salida_por_conversacion=True)
    raiz = tmp_path / "out"

    def crear_contexto(sesion_id: str) -> Contexto:
        return dataclasses.replace(
            contexto_de_conversacion(config, sesion_id, raiz), datos=DATOS_REALES
        )

    guion = [
        pide("proveedor_leer_solicitud", {"caso": PA}),
        pide("proveedor_mapear_campos", {"caso": PA}),
        responde("Listo."),
    ]
    app = crear_app(
        config,
        adaptador=AdaptadorFalso([*guion, *guion]),
        crear_contexto=crear_contexto,
        uso_diario=UsoDiario(raiz, tope_conversaciones=100, tope_usd=2.0),
    )
    cliente = TestClient(app)
    sesiones = [
        cliente.post("/api/chat", json={"message": "Prepara Panamá"}).json()["session_id"]
        for _ in range(2)
    ]
    for sesion in sesiones:
        assert (raiz / "sesiones" / sesion / PA / "mapeo.json").is_file()
    assert not (raiz / PA).exists()  # nada quedó en la carpeta compartida
    # Lo que ve la analista no lleva el id de la conversación en las rutas.
    resumen = cliente.get(f"/api/sessions/{sesiones[0]}").json()
    assert sesiones[0] not in json.dumps(resumen["turns"][0]["response"]["tool_calls"])
