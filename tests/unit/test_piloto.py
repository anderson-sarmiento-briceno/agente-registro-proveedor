"""Pruebas del piloto (Paso 21): los datos del piloto, las métricas y las opiniones. Sin red.

1. `preparar`: arma la carpeta del piloto (datos/ + piloto/casos/) y es válida.
2. `CARPETA_DATOS`: la aplicación lee de la carpeta del piloto si se indica.
3. Las métricas: O1 a O5 y la exactitud contra la respuesta correcta.
4. La planilla y las opiniones (👍 / 👎) entran al reporte.
"""

import dataclasses
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from registro_proveedor.agente.llm.falso import AdaptadorFalso, pide, responde
from registro_proveedor.api.aplicacion import crear_app
from registro_proveedor.api.limites import UsoDiario
from registro_proveedor.config import RAIZ_PROYECTO, Configuracion
from registro_proveedor.demo import ejecutar_demo
from registro_proveedor.herramientas.base import Contexto
from registro_proveedor.observabilidad import RegistroLlamada, escribir_auditoria
from registro_proveedor.piloto.metricas import leer_planilla, medir, reporte
from registro_proveedor.piloto.preparar import (
    CARPETA_PILOTO,
    ErrorDePiloto,
    casos_del_piloto,
    preparar,
)
from registro_proveedor.piloto.retroalimentacion import leer_opiniones
from tests.ayudas import DATOS_REALES

NUEVOS = ["co-constructora-andes", "ec-distribuidora-pacifico", "pe-mineria-del-sur"]
ESPERADO = CARPETA_PILOTO / "esperado"


@pytest.fixture
def datos_del_piloto(tmp_path: Path) -> Path:
    destino = tmp_path / "datos-del-piloto"
    assert preparar(destino).ok
    return destino


# ---------- 1. Preparar ----------


def test_la_carpeta_del_piloto_tiene_los_7_casos_y_es_valida(datos_del_piloto: Path) -> None:
    casos = sorted(p.name for p in (datos_del_piloto / "casos").iterdir())
    assert len(casos) == 7
    assert set(NUEVOS) <= set(casos)
    assert casos_del_piloto() == NUEVOS
    # Cada caso nuevo tiene su respuesta correcta para medir la exactitud.
    assert sorted(p.stem for p in ESPERADO.glob("*.json")) == NUEVOS


def test_solo_borra_una_carpeta_con_el_nombre_esperado(tmp_path: Path) -> None:
    with pytest.raises(ErrorDePiloto, match="por seguridad"):
        preparar(tmp_path / "otra-cosa")


def test_datos_no_se_toca(datos_del_piloto: Path) -> None:
    assert not any((DATOS_REALES / "casos" / caso).exists() for caso in NUEVOS)


# ---------- 2. CARPETA_DATOS ----------


def test_carpeta_datos() -> None:
    assert Configuracion().datos_efectivos() == RAIZ_PROYECTO / "datos"
    config = Configuracion(carpeta_datos=Path("piloto/datos-del-piloto"))
    assert config.datos_efectivos() == (RAIZ_PROYECTO / "piloto" / "datos-del-piloto").resolve()
    assert Contexto.desde_configuracion(config).datos == config.datos_efectivos()


# ---------- 3. Las métricas ----------


def _piloto_corrido(datos: Path, tmp_path: Path) -> Path:
    """Los 7 casos procesados por la demo (sin modelo), como si se hubieran trabajado."""
    salida = tmp_path / "out"
    assert ejecutar_demo(datos, salida, date(2026, 11, 26)).codigo == 0
    return salida


def test_metricas_de_los_objetivos(datos_del_piloto: Path, tmp_path: Path) -> None:
    salida = _piloto_corrido(datos_del_piloto, tmp_path)
    piloto = medir(salida, datos_del_piloto, ESPERADO, tmp_path / "sin-planilla.md")
    casos = {c.caso: c for c in piloto.casos}
    assert len(casos) == 7
    # O2: ningún valor inventado (todos salen del maestro).
    assert all(c.inventados == [] for c in casos.values())
    # O5: los soportes vencidos o por vencer quedan señalados en el checklist.
    assert all(c.soportes_senalados == c.soportes_alerta for c in casos.values())
    # Colombia (referencia) sigue listo; los de referencia no tienen respuesta correcta.
    assert casos["co-industrias-delta"].listo is True
    assert casos["co-industrias-delta"].o1 is None
    # Los nuevos sí: el mapeo no reconoce varias etiquetas escritas distinto.
    andes = casos["co-constructora-andes"]
    assert andes.o1 is not None and andes.o1 < 0.5
    assert andes.exactitud is not None
    assert "Tel." in andes.exactitud.no_reconocidos
    # Tras los ajustes del piloto: ningún dato queda en el campo equivocado, ni lleno ni
    # propuesto. «C.C. Representante Legal» y «NIT (sin dígito…)» quedan sin reconocer.
    assert andes.exactitud.errores == []
    assert andes.exactitud.propuestas_erroneas == []
    assert {"C.C. Representante Legal", "NIT (sin dígito de verificación)"} <= set(
        andes.exactitud.no_reconocidos
    )
    # …y como son obligatorios, el paquete NO queda listo (antes quedaba listo, vacío).
    assert andes.listo is False
    checklist = (salida / "co-constructora-andes" / "paquete" / "checklist.md").read_text("utf-8")
    assert "etiqueta no reconocida en un campo obligatorio: «Tel.»" in checklist


def test_el_reporte(datos_del_piloto: Path, tmp_path: Path) -> None:
    salida = _piloto_corrido(datos_del_piloto, tmp_path)
    texto = reporte(
        medir(salida, datos_del_piloto, ESPERADO, tmp_path / "sin-planilla.md"),
        datetime(2026, 11, 27, 10, 0),
    )
    assert "| O2 · Ningún valor inventado | 0 | 0 | ✅ |" in texto
    assert "| Tel. | `telefono` |" in texto  # sugerencia para el glosario
    assert "| O2 · Ningún valor en el campo equivocado (casos nuevos) | 0 | 0 | ✅ |" in texto
    assert "La planilla `piloto/planilla.md` todavía está vacía." in texto


def test_una_accion_sin_aprobacion_se_cuenta(datos_del_piloto: Path, tmp_path: Path) -> None:
    """O3: si alguna vez se ejecutara una confirmación sin aprobación, el reporte lo dice."""
    salida = _piloto_corrido(datos_del_piloto, tmp_path)
    escribir_auditoria(
        salida,
        RegistroLlamada(
            ts=datetime(2026, 11, 26, 12, 30, tzinfo=UTC),
            sesion="s",
            herramienta="proveedor_confirmar_campo",
            caso="pa-logistica-istmo",
            ok=True,
            resumen="RUC · aceptado",
            duracion_ms=1,
            aprobacion=None,
        ),
    )
    piloto = medir(salida, datos_del_piloto, ESPERADO, tmp_path / "sin-planilla.md")
    (panama,) = [c for c in piloto.casos if c.caso == "pa-logistica-istmo"]
    assert panama.acciones == 1 and panama.acciones_sin_aprobacion == 1


# ---------- 4. Planilla y opiniones ----------


def test_la_planilla_entra_al_reporte(tmp_path: Path) -> None:
    planilla = tmp_path / "planilla.md"
    planilla.write_text(
        "| Caso | Minutos a mano | Minutos con el agente | Errores encontrados | Comentarios |\n"
        "|---|---|---|---|---|\n"
        "| co-industrias-delta | 45 | 6,5 | Ninguno | Muy rápido |\n"
        "| ec-corp-andina | | | | |\n",
        encoding="utf-8",
    )
    filas = leer_planilla(planilla)
    assert len(filas) == 1  # la fila vacía no cuenta
    assert filas[0].minutos_a_mano == 45 and filas[0].minutos_con_agente == 6.5


def test_la_planilla_del_repositorio_se_puede_leer() -> None:
    assert leer_planilla(CARPETA_PILOTO / "planilla.md") is not None


def test_opinion_desde_el_chat(contexto: Contexto) -> None:
    app = crear_app(
        Configuracion(),
        adaptador=AdaptadorFalso(
            [pide("proveedor_leer_solicitud", {"caso": "pa-logistica-istmo"}), responde("Listo.")]
        ),
        crear_contexto=lambda sesion_id: dataclasses.replace(contexto, sesion_id=sesion_id),
        uso_diario=UsoDiario(contexto.salida, tope_conversaciones=100, tope_usd=2.0),
    )
    cliente = TestClient(app)
    sesion = cliente.post("/api/chat", json={"message": "Lee Panamá"}).json()["session_id"]
    r = cliente.post(
        "/api/feedback",
        json={"session_id": sesion, "turn": 0, "useful": False, "comment": "Faltó el RUC"},
    )
    assert r.status_code == 200 and r.json() == {"ok": True}
    (opinion,) = leer_opiniones(contexto.salida)
    assert opinion.util is False
    assert opinion.comentario == "Faltó el RUC"
    assert opinion.herramientas == ["proveedor_leer_solicitud"]
    assert opinion.casos == ["pa-logistica-istmo"]
    # Una respuesta que no existe, o una sesión inexistente: 404, y no se guarda nada.
    otra = {"session_id": sesion, "turn": 5, "useful": True}
    assert cliente.post("/api/feedback", json=otra).status_code == 404
    ajena = {"session_id": "0" * 32, "turn": 0, "useful": True}
    assert cliente.post("/api/feedback", json=ajena).status_code == 404
    assert len(leer_opiniones(contexto.salida)) == 1
    json.dumps([o.model_dump(mode="json") for o in leer_opiniones(contexto.salida)])
