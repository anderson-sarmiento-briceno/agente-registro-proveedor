"""Pruebas del adaptador del modelo de lenguaje (Paso 10). Sin red y sin clave.

Cómo se prueba el adaptador de Anthropic sin llamar a Anthropic:
    El SDK usa una librería HTTP (`httpx2`) que permite reemplazar la red por una
    función propia (`MockTransport`). Esa función recibe la solicitud que el SDK habría
    enviado (así se revisa QUÉ se manda) y devuelve una respuesta inventada con la forma
    exacta de la API (así se revisa cómo se INTERPRETA). Se ejercita el SDK de verdad,
    con sus errores, solo que sin red.

Cómo está organizado:
    1. Las herramientas que ve el modelo (salen solas del registro).
    2. Lo que se le envía a Anthropic.
    3. Cómo se interpreta su respuesta (texto, pedidos de herramienta, razonamiento).
    4. Errores traducidos a mensajes claros, sin la clave.
    5. El modelo falso de las pruebas.
    6. La prueba real (`probar_modelo.py`), con la red simulada.
"""

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from anthropic import DefaultHttpxClient

from registro_proveedor.agente.instrucciones import cargar_instrucciones
from registro_proveedor.agente.llm.adaptador import (
    BloqueTexto,
    DefinicionHerramienta,
    ErrorDelModelo,
    LlamadaHerramienta,
    Mensaje,
    MotivoFin,
    ResultadoHerramienta,
    Rol,
    Uso,
    definiciones_desde_registro,
)
from registro_proveedor.agente.llm.falso import AdaptadorFalso, pide, responde
from registro_proveedor.agente.llm.proveedor_anthropic import AdaptadorAnthropic
from registro_proveedor.agente.llm.prueba_real import costo_usd, probar
from registro_proveedor.config import Configuracion
from registro_proveedor.herramientas.proveedor import registro

CLAVE = "sk-ant-clave-de-prueba-que-no-debe-aparecer"
HERRAMIENTAS = definiciones_desde_registro(registro)

# ---------- Ayudas: la red simulada ----------

Manejador = Callable[[httpx2.Request], httpx2.Response]


def _config(**cambios: object) -> Configuracion:
    valores: dict[str, object] = {"anthropic_api_key": CLAVE, "llm_reintentos": 0, **cambios}
    return Configuracion(_env_file=None, **valores)  # type: ignore[call-arg]


def _adaptador(manejador: Manejador, **cambios: object) -> AdaptadorAnthropic:
    http = DefaultHttpxClient(transport=httpx2.MockTransport(manejador))
    return AdaptadorAnthropic.desde_configuracion(_config(**cambios), http_client=http)


def _respuesta_api(
    contenido: list[dict[str, Any]], motivo: str = "end_turn", **uso: int
) -> dict[str, Any]:
    """Una respuesta con la forma exacta de la API de Anthropic (POST /v1/messages)."""
    return {
        "id": "msg_prueba",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": contenido,
        "stop_reason": motivo,
        "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 30, **uso},
    }


class Grabadora:
    """Un manejador de red que guarda cada solicitud y devuelve una respuesta fija."""

    def __init__(self, respuesta: dict[str, Any], estado: int = 200) -> None:
        self.respuesta = respuesta
        self.estado = estado
        self.solicitudes: list[httpx2.Request] = []

    def __call__(self, solicitud: httpx2.Request) -> httpx2.Response:
        self.solicitudes.append(solicitud)
        return httpx2.Response(self.estado, json=self.respuesta)

    @property
    def cuerpo(self) -> dict[str, Any]:
        """El JSON de la última solicitud enviada."""
        datos = json.loads(self.solicitudes[-1].content)
        assert isinstance(datos, dict)
        return datos


TEXTO_OK = _respuesta_api([{"type": "text", "text": "Hola"}])


# ---------- 1. Las herramientas que ve el modelo ----------


def test_las_herramientas_salen_del_registro() -> None:
    nombres = [h.nombre for h in HERRAMIENTAS]
    assert nombres == [
        "proveedor_armar_paquete",
        "proveedor_confirmar_campo",
        "proveedor_generar_formulario",
        "proveedor_leer_solicitud",
        "proveedor_listar_casos",
        "proveedor_mapear_campos",
        "proveedor_registrar_envio",
    ]
    leer = next(h for h in HERRAMIENTAS if h.nombre == "proveedor_leer_solicitud")
    assert "país, el cliente, el formato" in leer.descripcion
    assert leer.parametros["required"] == ["caso"]
    assert leer.parametros["additionalProperties"] is False  # no acepta argumentos inventados


# ---------- 2. Lo que se le envía a Anthropic ----------


def test_lo_que_se_envia() -> None:
    red = Grabadora(TEXTO_OK)
    _adaptador(red).enviar("Eres el asistente.", [Mensaje.del_usuario("hola")], HERRAMIENTAS)
    cuerpo = red.cuerpo
    assert cuerpo["model"] == "claude-haiku-5-5"
    assert cuerpo["system"] == "Eres el asistente."
    assert cuerpo["output_config"] == {"effort": "medium"}  # CA6: esfuerzo, no temperature
    assert "temperature" not in cuerpo
    assert cuerpo["cache_control"] == {"type": "ephemeral"}  # CA7: caché del prompt
    assert cuerpo["max_tokens"] == 8000
    assert cuerpo["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hola"}]}]
    herramienta = cuerpo["tools"][0]
    assert set(herramienta) == {"name", "description", "input_schema"}
    assert herramienta["name"] == "proveedor_armar_paquete"


def test_la_configuracion_cambia_lo_que_se_envia() -> None:
    red = Grabadora(TEXTO_OK)
    adaptador = _adaptador(
        red, llm_modelo="claude-opus-5-5", llm_esfuerzo="low", llm_max_tokens=2000
    )
    adaptador.enviar("s", [Mensaje.del_usuario("hola")], [])
    assert (red.cuerpo["model"], red.cuerpo["output_config"], red.cuerpo["max_tokens"]) == (
        "claude-opus-5-5",
        {"effort": "low"},
        2000,
    )


def test_la_clave_va_en_el_encabezado_y_no_en_el_cuerpo() -> None:
    red = Grabadora(TEXTO_OK)
    _adaptador(red).enviar("s", [Mensaje.del_usuario("hola")], [])
    solicitud = red.solicitudes[-1]
    assert CLAVE in solicitud.headers["authorization"]
    assert CLAVE not in solicitud.content.decode()


def test_una_conversacion_con_herramientas() -> None:
    """Ida y vuelta: pedido del modelo → resultado de la herramienta, en el formato de Anthropic."""
    red = Grabadora(TEXTO_OK)
    pedido = Mensaje(
        rol=Rol.ASISTENTE,
        bloques=[
            BloqueTexto(texto="Busco el caso."),
            LlamadaHerramienta(
                id="t1", nombre="proveedor_listar_casos", argumentos={"filtro": "EC"}
            ),
        ],
    )
    resultado = Mensaje.con_resultados(
        [ResultadoHerramienta(id_llamada="t1", contenido='{"ok": false}', es_error=True)]
    )
    _adaptador(red).enviar("s", [Mensaje.del_usuario("el de Ecuador"), pedido, resultado], [])
    mensajes = red.cuerpo["messages"]
    assert mensajes[1] == {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Busco el caso."},
            {
                "type": "tool_use",
                "id": "t1",
                "name": "proveedor_listar_casos",
                "input": {"filtro": "EC"},
            },
        ],
    }
    assert mensajes[2] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "t1",
                "content": '{"ok": false}',
                "is_error": True,
            }
        ],
    }


def test_el_razonamiento_del_modelo_se_devuelve_tal_cual() -> None:
    """Anthropic exige recibir sin cambios los bloques "thinking" de su respuesta anterior."""
    contenido = [
        {"type": "thinking", "thinking": "", "signature": "firma-del-proveedor"},
        {"type": "tool_use", "id": "t1", "name": "proveedor_listar_casos", "input": {}},
    ]
    primera = _adaptador(Grabadora(_respuesta_api(contenido, "tool_use"))).enviar("s", [], [])
    assert primera.crudo == contenido  # se guarda todo, también el razonamiento
    assert len(primera.bloques) == 1  # pero el agente solo ve el pedido de herramienta

    red = Grabadora(TEXTO_OK)
    _adaptador(red).enviar("s", [Mensaje.del_usuario("hola"), primera.como_mensaje()], [])
    assert red.cuerpo["messages"][1] == {"role": "assistant", "content": contenido}


# ---------- 3. Cómo se interpreta la respuesta ----------


def test_respuesta_de_texto() -> None:
    respuesta = _adaptador(Grabadora(TEXTO_OK)).enviar("s", [Mensaje.del_usuario("hola")], [])
    assert respuesta.motivo is MotivoFin.TERMINO
    assert respuesta.texto == "Hola"
    assert respuesta.llamadas == []
    assert respuesta.modelo == "claude-haiku-5-5"


def test_respuesta_que_pide_herramientas() -> None:
    contenido = [
        {"type": "text", "text": "Voy a leer los dos casos."},
        {
            "type": "tool_use",
            "id": "t1",
            "name": "proveedor_leer_solicitud",
            "input": {"caso": "a"},
        },
        {
            "type": "tool_use",
            "id": "t2",
            "name": "proveedor_leer_solicitud",
            "input": {"caso": "b"},
        },
    ]
    respuesta = _adaptador(Grabadora(_respuesta_api(contenido, "tool_use"))).enviar("s", [], [])
    assert respuesta.motivo is MotivoFin.PIDE_HERRAMIENTA
    assert [(ll.id, ll.nombre, ll.argumentos) for ll in respuesta.llamadas] == [
        ("t1", "proveedor_leer_solicitud", {"caso": "a"}),
        ("t2", "proveedor_leer_solicitud", {"caso": "b"}),
    ]
    assert respuesta.texto == "Voy a leer los dos casos."


@pytest.mark.parametrize(
    ("motivo_api", "motivo"),
    [
        ("end_turn", MotivoFin.TERMINO),
        ("tool_use", MotivoFin.PIDE_HERRAMIENTA),
        ("max_tokens", MotivoFin.LIMITE_TOKENS),
        ("pause_turn", MotivoFin.PAUSA),
        ("refusal", MotivoFin.RECHAZO),
    ],
)
def test_motivos_de_fin(motivo_api: str, motivo: MotivoFin) -> None:
    respuesta = _adaptador(Grabadora(_respuesta_api([], motivo_api))).enviar("s", [], [])
    assert respuesta.motivo is motivo


def test_uso_de_tokens_y_cache() -> None:
    datos = _respuesta_api([], cache_read_input_tokens=900, cache_creation_input_tokens=50)
    uso = _adaptador(Grabadora(datos)).enviar("s", [], []).uso
    assert (uso.entrada, uso.salida, uso.cache_lectura, uso.cache_escritura) == (120, 30, 900, 50)


# ---------- 4. Errores claros y sin la clave ----------


def _error(estado: int, tipo: str) -> dict[str, Any]:
    return {"type": "error", "error": {"type": tipo, "message": "detalle del proveedor"}}


@pytest.mark.parametrize(
    ("estado", "tipo", "codigo", "reintentable", "texto"),
    [
        (401, "authentication_error", "autenticacion", False, "revise ANTHROPIC_API_KEY"),
        (403, "permission_error", "permiso", False, "no tiene permiso"),
        (404, "not_found_error", "modelo_inexistente", False, "revise LLM_MODELO"),
        (400, "invalid_request_error", "solicitud_invalida", False, "rechazó la solicitud"),
        (429, "rate_limit_error", "limite_de_uso", True, "límite de uso"),
        (500, "api_error", "servicio_no_disponible", True, "saturado o tuvo una falla"),
        (529, "overloaded_error", "servicio_no_disponible", True, "saturado o tuvo una falla"),
    ],
)
def test_errores_del_proveedor(
    estado: int, tipo: str, codigo: str, reintentable: bool, texto: str
) -> None:
    adaptador = _adaptador(Grabadora(_error(estado, tipo), estado))
    with pytest.raises(ErrorDelModelo) as error:
        adaptador.enviar("s", [Mensaje.del_usuario("hola")], [])
    assert error.value.codigo == codigo
    assert error.value.reintentable is reintentable
    assert texto in error.value.mensaje
    assert CLAVE not in str(error.value)


def test_timeout() -> None:
    def lento(solicitud: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("demasiado lento", request=solicitud)

    with pytest.raises(ErrorDelModelo) as error:
        _adaptador(lento).enviar("s", [Mensaje.del_usuario("hola")], [])
    assert (error.value.codigo, error.value.reintentable) == ("timeout", True)


def test_sin_conexion() -> None:
    def caido(solicitud: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("sin red", request=solicitud)

    with pytest.raises(ErrorDelModelo) as error:
        _adaptador(caido).enviar("s", [Mensaje.del_usuario("hola")], [])
    assert (error.value.codigo, error.value.reintentable) == ("sin_conexion", True)


def test_sin_ninguna_clave(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin clave, el SDK falla ANTES de llamar a la red; el error llega igual de claro."""
    for variable in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(variable, raising=False)
    red = Grabadora(TEXTO_OK)
    http = DefaultHttpxClient(transport=httpx2.MockTransport(red))
    config = Configuracion(_env_file=None, llm_reintentos=0)  # type: ignore[call-arg]
    adaptador = AdaptadorAnthropic.desde_configuracion(config, http_client=http)
    with pytest.raises(ErrorDelModelo) as error:
        adaptador.enviar("s", [Mensaje.del_usuario("hola")], [])
    assert error.value.codigo == "sin_clave"
    assert "ANTHROPIC_API_KEY" in error.value.mensaje
    assert red.solicitudes == []  # no se llegó a llamar a la red


def test_los_reintentos_los_hace_el_sdk() -> None:
    """Con 2 reintentos, un 529 se intenta 3 veces y, si sigue fallando, da el error claro."""
    red = Grabadora(_error(529, "overloaded_error"), 529)
    adaptador = _adaptador(red, llm_reintentos=2)
    with pytest.raises(ErrorDelModelo):
        adaptador.enviar("s", [Mensaje.del_usuario("hola")], [])
    assert len(red.solicitudes) == 3


def test_un_error_que_no_vale_la_pena_reintentar_no_se_reintenta() -> None:
    red = Grabadora(_error(401, "authentication_error"), 401)
    with pytest.raises(ErrorDelModelo):
        _adaptador(red, llm_reintentos=2).enviar("s", [Mensaje.del_usuario("hola")], [])
    assert len(red.solicitudes) == 1


# ---------- 5. El modelo falso ----------


def test_el_modelo_falso_sigue_su_guion_y_guarda_lo_que_recibe() -> None:
    falso = AdaptadorFalso(
        [pide("proveedor_listar_casos", {"filtro": "Ecuador"}), responde("Es ec-corp-andina.")]
    )
    primera = falso.enviar("sistema", [Mensaje.del_usuario("el de Ecuador")], HERRAMIENTAS)
    segunda = falso.enviar("sistema", [], [])
    assert primera.motivo is MotivoFin.PIDE_HERRAMIENTA
    assert primera.llamadas[0].nombre == "proveedor_listar_casos"
    assert segunda.texto == "Es ec-corp-andina."
    assert len(falso.envios) == 2
    assert falso.envios[0].mensajes[0].bloques == [BloqueTexto(texto="el de Ecuador")]
    assert len(falso.envios[0].herramientas) == len(HERRAMIENTAS)


def test_el_modelo_falso_puede_simular_un_error() -> None:
    caida = ErrorDelModelo("caído", reintentable=True, codigo="servicio_no_disponible")
    falso = AdaptadorFalso([caida])
    with pytest.raises(ErrorDelModelo, match="caído"):
        falso.enviar("s", [], [])


def test_el_modelo_falso_avisa_si_se_acaba_el_guion() -> None:
    with pytest.raises(AssertionError, match="se quedó sin respuestas"):
        AdaptadorFalso([]).enviar("s", [], [])


def test_las_definiciones_son_inmutables() -> None:
    definicion = DefinicionHerramienta(nombre="x", descripcion="y", parametros={})
    with pytest.raises(ValueError, match="frozen"):
        definicion.nombre = "otro"  # type: ignore[misc]


# ---------- 6. La prueba real, con la red simulada ----------


def test_prueba_real_muestra_la_herramienta_que_pidio() -> None:
    contenido = [
        {
            "type": "tool_use",
            "id": "t1",
            "name": "proveedor_listar_casos",
            "input": {"filtro": "Ecuador"},
        }
    ]
    red = Grabadora(_respuesta_api(contenido, "tool_use", cache_creation_input_tokens=800))
    http = DefaultHttpxClient(transport=httpx2.MockTransport(red))
    codigo, texto = probar(_config(), "busca el de Ecuador", http_client=http)
    assert codigo == 0
    assert red.cuerpo["messages"][0]["content"][0]["text"] == "busca el de Ecuador"
    assert len(red.cuerpo["tools"]) == 7  # le ofreció todas las herramientas
    assert "Resultado: pide herramientas" in texto
    assert '| 1 | proveedor_listar_casos | {"filtro": "Ecuador"} |' in texto
    assert "Herramientas ofrecidas (7)" in texto
    assert CLAVE not in texto
    # Envía las instrucciones reales del agente (Paso 11) y muestra su versión.
    assert red.cuerpo["system"] == cargar_instrucciones().texto
    assert f"Instrucciones: versión {cargar_instrucciones().version}" in texto


def test_costo_con_cache() -> None:
    """Los tokens de la llamada real: 4 de entrada, 60 de salida y 2056 guardados en caché."""
    primera = costo_usd(Uso(entrada=4, salida=60, cache_escritura=2056))
    assert primera == pytest.approx((4 + 2056 * 1.25) * 0.10 / 1e6 + 60 * 0.50 / 1e6)
    # La segunda vez, lo mismo se LEE de la caché: mucho más barato.
    segunda = costo_usd(Uso(entrada=4, salida=60, cache_lectura=2056))
    assert segunda < primera / 3


def test_prueba_real_sin_clave(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin clave el resultado es un error claro, no una excepción."""

    def falla(config: Configuracion, http_client: object = None) -> AdaptadorAnthropic:
        raise ErrorDelModelo("no hay una clave", reintentable=False, codigo="sin_clave")

    monkeypatch.setattr(AdaptadorAnthropic, "desde_configuracion", staticmethod(falla))
    codigo, texto = probar(_config(), "hola")
    assert codigo == 1
    assert texto == "ERROR (sin_clave): no hay una clave"
