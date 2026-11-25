"""Pruebas del ciclo del agente (Paso 12). Sin red: con el modelo falso y su guion.

Cada prueba escribe el guion de lo que "responde" el modelo y revisa qué hizo el ciclo:
qué herramientas ejecutó y en qué orden, qué le mandó al modelo y qué le mostró a la
analista. Las herramientas son las REALES, sobre los datos reales, escribiendo en un
`out/` temporal.

Cómo está organizado:
    1. El flujo normal: un caso completo, en el orden de la matriz.
    2. Lo que recibe el modelo: sistema, herramientas y resultados enmascarados.
    3. Errores de herramientas: inexistente, argumentos inventados, varias a la vez.
    4. CA3: una herramienta que requiere aprobación NO se ejecuta.
    5. CA1: topes de consultas y de tokens.
    6. CA5: errores del modelo y respuestas raras; la sesión sigue viva.
    7. El chat de la terminal.
"""

import itertools
import json
from collections.abc import Iterator

import pytest
from structlog.testing import capture_logs

from registro_proveedor.agente.chat_terminal import conversar
from registro_proveedor.agente.ciclo import SIN_APROBACION, Agente, FinTurno, Sesion
from registro_proveedor.agente.instrucciones import cargar_instrucciones
from registro_proveedor.agente.llm.adaptador import (
    BloqueTexto,
    ErrorDelModelo,
    Mensaje,
    MotivoFin,
    RespuestaModelo,
    ResultadoHerramienta,
    Rol,
    Uso,
)
from registro_proveedor.agente.llm.falso import AdaptadorFalso, pide, pide_varias, responde
from registro_proveedor.agente.llm.proveedor_anthropic import AdaptadorAnthropic
from registro_proveedor.config import Configuracion
from registro_proveedor.herramientas.base import Contexto
from registro_proveedor.herramientas.proveedor import registro
from tests.ayudas import DATOS_REALES

CO = "co-industrias-delta"
EC = "ec-corp-andina"
INSTRUCCIONES = cargar_instrucciones()

# Las herramientas de un caso completo, en el orden de la matriz de `demo.py --llamadas`
# (precedidas por la búsqueda del caso).
ORDEN_DEL_FLUJO = [
    "proveedor_listar_casos",
    "proveedor_leer_solicitud",
    "proveedor_mapear_campos",
    "proveedor_generar_formulario",
    "proveedor_armar_paquete",
]


def _agente(falso: AdaptadorFalso, **topes: int) -> Agente:
    return Agente(adaptador=falso, registro=registro, instrucciones=INSTRUCCIONES, **topes)


def _guion_caso_completo(caso: str = CO) -> list[RespuestaModelo | ErrorDelModelo]:
    return [
        pide("proveedor_listar_casos", {"filtro": "Colombia"}),
        pide("proveedor_leer_solicitud", {"caso": caso}),
        pide("proveedor_mapear_campos", {"caso": caso}),
        pide("proveedor_generar_formulario", {"caso": caso}),
        pide("proveedor_armar_paquete", {"caso": caso}),
        responde("**Caso:** co-industrias-delta · listo para firma. ¿Revisamos otro caso?"),
    ]


def _resultados(mensaje: Mensaje) -> list[ResultadoHerramienta]:
    return [b for b in mensaje.bloques if isinstance(b, ResultadoHerramienta)]


def _con_uso(respuesta: RespuestaModelo, tokens: int) -> RespuestaModelo:
    return respuesta.model_copy(update={"uso": Uso(entrada=tokens)})


# ---------- 1. El flujo normal ----------


def test_caso_completo_en_el_orden_de_la_matriz(contexto: Contexto) -> None:
    falso = AdaptadorFalso(_guion_caso_completo())
    sesion = Sesion(contexto)
    turno = _agente(falso).responder(sesion, "Prepara el caso de Colombia")

    assert turno.fin is FinTurno.RESPONDIO
    assert turno.texto.startswith("**Caso:** co-industrias-delta")
    assert [ll.nombre for ll in turno.llamadas] == ORDEN_DEL_FLUJO
    assert [ll.orden for ll in turno.llamadas] == [1, 2, 3, 4, 5]
    assert all(ll.ok for ll in turno.llamadas)
    assert turno.consultas == 6
    # El resumen de cada llamada es el mismo de log.jsonl.
    assert turno.llamadas[-1].resumen == f"out/{CO}/paquete · listo para firma"
    # Las herramientas trabajaron de verdad.
    assert (contexto.salida / CO / "paquete" / "checklist.md").is_file()
    # Historial: usuario, 5 veces (pedido + resultados), respuesta final.
    roles = [m.rol for m in sesion.mensajes]
    assert len(roles) == 12
    assert roles == [Rol.USUARIO] + [Rol.ASISTENTE, Rol.USUARIO] * 5 + [Rol.ASISTENTE]


def test_la_conversacion_sigue_en_el_turno_siguiente(contexto: Contexto) -> None:
    falso = AdaptadorFalso([*_guion_caso_completo(), responde("Con gusto.")])
    sesion = Sesion(contexto)
    agente = _agente(falso)
    agente.responder(sesion, "Prepara el caso de Colombia")
    turno = agente.responder(sesion, "Gracias")
    assert turno.texto == "Con gusto."
    assert turno.llamadas == ()
    # El modelo recibió TODO el historial, con el mensaje nuevo al final.
    ultimo_envio = falso.envios[-1].mensajes
    assert len(ultimo_envio) == 13
    assert ultimo_envio[-1] == Mensaje.del_usuario("Gracias")


def test_cada_consulta_queda_en_el_log_con_la_version_del_prompt(contexto: Contexto) -> None:
    falso = AdaptadorFalso([pide("proveedor_listar_casos", {}), responde("Hay 4 casos.")])
    with capture_logs() as eventos:
        _agente(falso).responder(Sesion(contexto), "¿Qué casos hay?")
    consultas = [e for e in eventos if e["event"] == "consulta_modelo"]
    assert len(consultas) == 2
    assert consultas[0]["instrucciones_version"] == INSTRUCCIONES.version
    assert consultas[0]["instrucciones_huella"] == INSTRUCCIONES.huella
    assert consultas[0]["herramientas_pedidas"] == ["proveedor_listar_casos"]
    assert consultas[1]["motivo"] == "termino"


# ---------- 2. Lo que recibe el modelo ----------


def test_el_modelo_recibe_las_instrucciones_y_las_herramientas(contexto: Contexto) -> None:
    falso = AdaptadorFalso([responde("Hola, ¿en qué caso trabajamos?")])
    _agente(falso).responder(Sesion(contexto), "Hola")
    envio = falso.envios[0]
    assert envio.sistema == INSTRUCCIONES.texto
    assert {h.nombre for h in envio.herramientas} == {h.nombre for h in registro.listar()}


def test_el_numero_de_cuenta_nunca_llega_al_modelo(contexto: Contexto) -> None:
    """RN8: lo que va al modelo son los resultados enmascarados (`a_json`)."""
    maestro = json.loads((DATOS_REALES / "repositorio" / "maestro.json").read_text("utf-8"))
    cuenta = maestro["banco"]["numero_cuenta"]
    falso = AdaptadorFalso(_guion_caso_completo())
    _agente(falso).responder(Sesion(contexto), "Prepara el caso de Colombia")
    enviado = " ".join(m.model_dump_json() for m in falso.envios[-1].mensajes)
    assert cuenta not in enviado
    assert "****" + cuenta[-4:] in enviado  # sí llega, pero enmascarado


# ---------- 3. Errores de herramientas: llegan al modelo como resultado ----------


def test_varias_herramientas_a_la_vez_en_orden(contexto: Contexto) -> None:
    falso = AdaptadorFalso(
        [
            pide_varias(
                [
                    ("proveedor_leer_solicitud", {"caso": CO}, "a"),
                    ("proveedor_leer_solicitud", {"caso": EC}, "b"),
                ]
            ),
            responde("Leí los dos."),
        ]
    )
    sesion = Sesion(contexto)
    turno = _agente(falso).responder(sesion, "Lee los casos de Colombia y Ecuador")
    assert [ll.argumentos for ll in turno.llamadas] == [{"caso": CO}, {"caso": EC}]
    # Los dos resultados van JUNTOS, en un solo mensaje, con el id de cada pedido.
    resultados = _resultados(sesion.mensajes[2])
    assert [r.id_llamada for r in resultados] == ["a", "b"]
    assert turno.consultas == 2


def test_herramienta_inexistente_vuelve_como_error(contexto: Contexto) -> None:
    falso = AdaptadorFalso(
        [pide("proveedor_enviar_correo", {"caso": CO}), responde("No puedo enviar correos.")]
    )
    sesion = Sesion(contexto)
    turno = _agente(falso).responder(sesion, "Envía el correo")
    assert turno.fin is FinTurno.RESPONDIO  # el turno sigue: el modelo explica
    assert not turno.llamadas[0].ok
    assert "no existe la herramienta" in turno.llamadas[0].resumen
    resultado = _resultados(sesion.mensajes[2])[0]
    assert resultado.es_error


def test_argumentos_inventados_vuelven_como_error(contexto: Contexto) -> None:
    falso = AdaptadorFalso(
        [pide("proveedor_leer_solicitud", {"caso": CO, "enviar": True}), responde("Listo.")]
    )
    turno = _agente(falso).responder(Sesion(contexto), "Lee el caso")
    assert not turno.llamadas[0].ok
    assert "argumentos no válidos" in turno.llamadas[0].resumen


def test_caso_inexistente_vuelve_como_error(contexto: Contexto) -> None:
    falso = AdaptadorFalso(
        [pide("proveedor_leer_solicitud", {"caso": "co-no-existe"}), responde("No existe.")]
    )
    turno = _agente(falso).responder(Sesion(contexto), "Lee el caso")
    assert not turno.llamadas[0].ok
    assert "proveedor_listar_casos" in turno.llamadas[0].resumen  # le dice cómo seguir


# ---------- 4. CA3: lo que requiere aprobación no se ejecuta ----------


def test_confirmar_campo_no_se_ejecuta_sin_aprobacion(contexto: Contexto) -> None:
    falso = AdaptadorFalso(
        [
            pide("proveedor_mapear_campos", {"caso": EC}),
            pide(
                "proveedor_confirmar_campo",
                {"caso": EC, "etiqueta": "RUC", "decision": "aceptar"},
            ),
            responde("El campo sigue por confirmar."),
        ]
    )
    sesion = Sesion(contexto)
    turno = _agente(falso).responder(sesion, "Mapea el caso de Ecuador y acepta el RUC")

    confirmar = turno.llamadas[1]
    assert confirmar.nombre == "proveedor_confirmar_campo"
    assert not confirmar.ok
    assert "aprobación" in confirmar.resumen
    # El mapeo guardado no tiene ninguna decisión: no se confirmó nada.
    mapeo = json.loads((contexto.salida / EC / "mapeo.json").read_text(encoding="utf-8"))
    assert all(campo.get("confirmacion") is None for campo in mapeo["campos"])
    assert any(campo["estado"] == "requiere_confirmacion" for campo in mapeo["campos"])
    # El modelo recibe el motivo, como error.
    resultado = _resultados(sesion.mensajes[4])[0]
    assert resultado.es_error
    assert SIN_APROBACION in resultado.contenido
    # Y queda en la auditoría del caso.
    lineas = (contexto.salida / EC / "log.jsonl").read_text(encoding="utf-8").splitlines()
    ultima = json.loads(lineas[-1])
    assert ultima["herramienta"] == "proveedor_confirmar_campo"
    assert ultima["ok"] is False
    assert "requiere aprobación" in ultima["resumen"]


# ---------- 5. CA1: topes ----------


def test_tope_de_consultas_responde_con_lo_que_tiene(contexto: Contexto) -> None:
    falso = AdaptadorFalso(_guion_caso_completo())
    sesion = Sesion(contexto)
    turno = _agente(falso, max_iteraciones=2).responder(sesion, "Prepara el caso de Colombia")

    assert turno.fin is FinTurno.TOPE_ITERACIONES
    assert turno.consultas == 2
    assert [ll.nombre for ll in turno.llamadas] == ORDEN_DEL_FLUJO[:2]
    assert "tope de 2 consultas" in turno.texto
    assert "1. ✓ proveedor_listar_casos" in turno.texto
    assert "2. ✓ proveedor_leer_solicitud" in turno.texto
    assert "«sigue»" in turno.texto
    assert len(falso.envios) == 2  # no hubo una tercera consulta


def test_despues_del_tope_se_puede_seguir(contexto: Contexto) -> None:
    falso = AdaptadorFalso(_guion_caso_completo())
    sesion = Sesion(contexto)
    agente = _agente(falso, max_iteraciones=2)
    agente.responder(sesion, "Prepara el caso de Colombia")
    agente.responder(sesion, "sigue")
    turno = agente.responder(sesion, "sigue")
    assert turno.fin is FinTurno.RESPONDIO
    # La conversación siempre alterna usuario / asistente: "sigue" se unió a los
    # resultados de las herramientas, que ya eran un mensaje del usuario.
    roles = [m.rol for m in sesion.mensajes]
    assert all(a != b for a, b in itertools.pairwise(roles))
    unido = sesion.mensajes[4]
    assert isinstance(unido.bloques[0], ResultadoHerramienta)
    assert unido.bloques[-1] == BloqueTexto(texto="sigue")


def test_tope_de_tokens_por_sesion(contexto: Contexto) -> None:
    falso = AdaptadorFalso(
        [_con_uso(pide("proveedor_listar_casos", {}), 1_500), responde("no debería llegar")]
    )
    sesion = Sesion(contexto)
    agente = _agente(falso, tope_tokens_sesion=1_000)
    turno = agente.responder(sesion, "¿Qué casos hay?")

    assert turno.fin is FinTurno.TOPE_TOKENS
    assert turno.consultas == 1
    assert "tope de 1 000 tokens" in turno.texto
    assert "1. ✓ proveedor_listar_casos" in turno.texto
    assert "conversación nueva" in turno.texto
    # La sesión ya gastó su tope: el turno siguiente ni consulta al modelo.
    otro = agente.responder(sesion, "sigue")
    assert otro.fin is FinTurno.TOPE_TOKENS
    assert otro.consultas == 0
    assert len(falso.envios) == 1


def test_los_tokens_se_acumulan_por_turno_y_por_sesion(contexto: Contexto) -> None:
    falso = AdaptadorFalso(
        [
            _con_uso(pide("proveedor_listar_casos", {}), 100),
            _con_uso(responde("Hay 4."), 50),
            _con_uso(responde("De nada."), 30),
        ]
    )
    sesion = Sesion(contexto)
    agente = _agente(falso)
    assert agente.responder(sesion, "¿Casos?").uso.total == 150
    assert agente.responder(sesion, "Gracias").uso.total == 30
    assert sesion.uso.total == 180


def test_uso_total_y_suma() -> None:
    a = Uso(entrada=1, salida=2, cache_lectura=3, cache_escritura=4)
    assert a.total == 10
    assert a.sumar(a) == Uso(entrada=2, salida=4, cache_lectura=6, cache_escritura=8)


# ---------- 6. CA5: errores del modelo y respuestas raras ----------


def test_error_del_modelo_no_cierra_la_sesion(contexto: Contexto) -> None:
    error = ErrorDelModelo("no hay conexión", reintentable=True, codigo="sin_conexion")
    falso = AdaptadorFalso([error, responde("Ahora sí: hay 4 casos.")])
    sesion = Sesion(contexto)
    agente = _agente(falso)

    turno = agente.responder(sesion, "¿Qué casos hay?")
    assert turno.fin is FinTurno.ERROR_MODELO
    assert turno.texto == (
        "No pude comunicarme con el modelo: no hay conexión. "
        "Intente de nuevo en un momento. La conversación sigue abierta."
    )
    # Se reintenta escribiendo otra vez: la sesión sigue y el modelo recibe los dos textos.
    otro = agente.responder(sesion, "¿Qué casos hay?")
    assert otro.fin is FinTurno.RESPONDIO
    assert len(falso.envios[-1].mensajes) == 1
    assert len(falso.envios[-1].mensajes[0].bloques) == 2


def test_error_a_mitad_de_turno_muestra_lo_hecho(contexto: Contexto) -> None:
    error = ErrorDelModelo("la clave no es válida", reintentable=False, codigo="autenticacion")
    falso = AdaptadorFalso([pide("proveedor_leer_solicitud", {"caso": CO}), error])
    turno = _agente(falso).responder(Sesion(contexto), "Lee el caso de Colombia")
    assert turno.fin is FinTurno.ERROR_MODELO
    assert "Intente de nuevo" not in turno.texto  # no es pasajero
    assert "1. ✓ proveedor_leer_solicitud" in turno.texto


def test_error_queda_en_el_log_sin_la_clave(contexto: Contexto) -> None:
    error = ErrorDelModelo("límite", reintentable=True, codigo="limite_de_uso")
    with capture_logs() as eventos:
        _agente(AdaptadorFalso([error])).responder(Sesion(contexto), "hola")
    (evento,) = [e for e in eventos if e["event"] == "error_del_modelo"]
    assert evento["codigo"] == "limite_de_uso"


def test_respuesta_cortada_avisa(contexto: Contexto) -> None:
    falso = AdaptadorFalso([responde("Resumen a medias", MotivoFin.LIMITE_TOKENS)])
    turno = _agente(falso).responder(Sesion(contexto), "Resume")
    assert turno.fin is FinTurno.INCOMPLETA
    assert turno.texto.startswith("Resumen a medias\n\n(La respuesta quedó incompleta.")


def test_pedido_cortado_no_entra_al_historial(contexto: Contexto) -> None:
    """Un pedido de herramienta sin su resultado haría fallar la consulta siguiente."""
    cortado = pide("proveedor_listar_casos", {}).model_copy(
        update={"motivo": MotivoFin.LIMITE_TOKENS}
    )
    sesion = Sesion(contexto)
    turno = _agente(AdaptadorFalso([cortado])).responder(sesion, "¿Casos?")
    assert turno.fin is FinTurno.INCOMPLETA
    assert turno.llamadas == ()  # no se ejecutó
    assert [m.rol for m in sesion.mensajes] == [Rol.USUARIO]


def test_rechazo(contexto: Contexto) -> None:
    falso = AdaptadorFalso([responde("", MotivoFin.RECHAZO)])
    turno = _agente(falso).responder(Sesion(contexto), "algo indebido")
    assert turno.fin is FinTurno.RECHAZO
    assert "no quiso responder" in turno.texto


def test_respuesta_vacia_no_entra_al_historial(contexto: Contexto) -> None:
    sesion = Sesion(contexto)
    turno = _agente(AdaptadorFalso([responde("  ")])).responder(sesion, "hola")
    assert turno.fin is FinTurno.RESPONDIO
    assert "sin escribir una respuesta" in turno.texto
    assert [m.rol for m in sesion.mensajes] == [Rol.USUARIO]


# ---------- 7. El chat de la terminal ----------


def _persona(*mensajes: str) -> Iterator[str]:
    yield from mensajes


def test_chat_muestra_las_herramientas_en_orden(contexto: Contexto) -> None:
    escrito: list[str] = []
    persona = _persona("Prepara el caso de Colombia", "", "salir")
    codigo = conversar(
        Configuracion(),
        leer=lambda _prompt: next(persona),
        escribir=escrito.append,
        adaptador=AdaptadorFalso(_guion_caso_completo()),
        sesion=Sesion(contexto),
    )
    assert codigo == 0
    texto = "\n".join(escrito)
    assert "| # | Herramienta | Argumentos | Resultado |" in texto
    for orden, nombre in enumerate(ORDEN_DEL_FLUJO, start=1):
        assert f"| {orden} | {nombre} |" in texto
    assert '| 2 | proveedor_leer_solicitud | {"caso": "co-industrias-delta"} | ✓' in texto
    assert "Fin: respondio · 6 consultas al modelo" in texto
    assert "Fin de la conversación" in texto


def test_chat_termina_con_fin_de_entrada(contexto: Contexto) -> None:
    def sin_entrada(_prompt: str) -> str:
        raise EOFError

    escrito: list[str] = []
    codigo = conversar(
        Configuracion(),
        leer=sin_entrada,
        escribir=escrito.append,
        adaptador=AdaptadorFalso([]),
        sesion=Sesion(contexto),
    )
    assert codigo == 0
    assert "Fin de la conversación" in escrito[-1]


def test_chat_sin_clave(monkeypatch: pytest.MonkeyPatch) -> None:
    def falla(config: Configuracion, http_client: object = None) -> AdaptadorAnthropic:
        raise ErrorDelModelo("no hay una clave", reintentable=False, codigo="sin_clave")

    monkeypatch.setattr(AdaptadorAnthropic, "desde_configuracion", staticmethod(falla))
    escrito: list[str] = []
    assert conversar(Configuracion(), leer=input, escribir=escrito.append) == 1
    assert escrito == ["ERROR: no hay una clave"]


def test_sesion_nueva_tiene_su_propio_id() -> None:
    config = Configuracion()
    a, b = Sesion.nueva(config), Sesion.nueva(config)
    assert a.id != b.id
    assert a.contexto.sesion_id == a.id
