"""Pruebas de los topes de la demo abierta y de los precios (Paso 18). Sin red.

1. Por visitante: conversaciones por hora y mensajes por minuto, con un reloj falso.
2. Por día: conversaciones y dólares; se guarda en un archivo y cambia con el día.
3. Precios: un modelo desconocido nunca cuesta cero.
4. Costo por caso: la suma de out/costos.jsonl.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from registro_proveedor.agente.llm.adaptador import Uso
from registro_proveedor.agente.llm.costos import (
    PRECIO_DE_RESGUARDO,
    costo_usd,
    precio_conocido,
    precio_de,
)
from registro_proveedor.api.limites import (
    ARCHIVO_USO_DIARIO,
    DEMASIADAS_CONVERSACIONES,
    DEMASIADOS_MENSAJES,
    TOPE_DIARIO_CONVERSACIONES,
    TOPE_DIARIO_DINERO,
    LimitadorPorVisitante,
    UsoDiario,
)
from registro_proveedor.observabilidad import (
    SIN_CASO,
    RegistroCosto,
    costo_por_caso,
    escribir_costo,
    tabla_de_costos,
)


class Reloj:
    """Un reloj que avanza solo cuando la prueba lo pide."""

    def __init__(self) -> None:
        self.ahora = 1000.0

    def __call__(self) -> float:
        return self.ahora


# ---------- 1. Por visitante ----------


def _limitador(reloj: Reloj) -> LimitadorPorVisitante:
    return LimitadorPorVisitante(conversaciones_por_hora=2, mensajes_por_minuto=3, reloj=reloj)


def test_mensajes_por_minuto() -> None:
    reloj = Reloj()
    limitador = _limitador(reloj)
    assert [limitador.permitir_mensaje("1.1.1.1") for _ in range(3)] == [None] * 3
    assert limitador.permitir_mensaje("1.1.1.1") == DEMASIADOS_MENSAJES
    # Otro visitante no se ve afectado.
    assert limitador.permitir_mensaje("2.2.2.2") is None
    # Pasado el minuto, vuelve a poder.
    reloj.ahora += 60
    assert limitador.permitir_mensaje("1.1.1.1") is None


def test_conversaciones_por_hora() -> None:
    reloj = Reloj()
    limitador = _limitador(reloj)
    assert limitador.permitir_conversacion("1.1.1.1") is None
    reloj.ahora += 1800
    assert limitador.permitir_conversacion("1.1.1.1") is None
    assert limitador.permitir_conversacion("1.1.1.1") == DEMASIADAS_CONVERSACIONES
    # La ventana es deslizante: a la hora de la PRIMERA, se libera un cupo.
    reloj.ahora += 1800
    assert limitador.permitir_conversacion("1.1.1.1") is None
    assert limitador.permitir_conversacion("1.1.1.1") == DEMASIADAS_CONVERSACIONES


def test_olvida_a_los_visitantes_inactivos() -> None:
    reloj = Reloj()
    limitador = _limitador(reloj)
    for i in range(50):
        limitador.permitir_mensaje(f"10.0.0.{i}")
    reloj.ahora += 61
    limitador.permitir_mensaje("10.0.1.1")
    assert len(limitador._mensajes) == 1  # los 50 anteriores ya no ocupan memoria


# ---------- 2. Por día ----------


class Dia:
    def __init__(self) -> None:
        self.hoy = date(2026, 11, 26)

    def __call__(self) -> date:
        return self.hoy


def _diario(carpeta: Path, dia: Dia, **topes: float) -> UsoDiario:
    return UsoDiario(
        carpeta,
        tope_conversaciones=int(topes.get("conversaciones", 2)),
        tope_usd=topes.get("usd", 1.0),
        hoy=dia,
    )


def test_tope_diario_de_conversaciones(tmp_path: Path) -> None:
    diario = _diario(tmp_path, Dia())
    for _ in range(2):
        assert diario.motivo_para_no_abrir() is None
        diario.contar_conversacion()
    assert diario.motivo_para_no_abrir() == TOPE_DIARIO_CONVERSACIONES
    # Las conversaciones ya abiertas pueden seguir: solo el dinero las detiene.
    assert diario.motivo_para_no_seguir() is None


def test_tope_diario_de_dinero(tmp_path: Path) -> None:
    diario = _diario(tmp_path, Dia(), usd=0.05)
    diario.sumar(0.03)
    assert diario.motivo_para_no_seguir() is None
    diario.sumar(0.03)
    assert diario.motivo_para_no_seguir() == TOPE_DIARIO_DINERO
    assert diario.motivo_para_no_abrir() == TOPE_DIARIO_DINERO


def test_un_reinicio_no_borra_el_conteo(tmp_path: Path) -> None:
    dia = Dia()
    primero = _diario(tmp_path, dia)
    primero.contar_conversacion()
    primero.sumar(0.25)
    # "Se reinicia el servidor": otro objeto lee el mismo archivo.
    segundo = _diario(tmp_path, dia)
    assert segundo.hoy == (1, 0.25)


def test_al_dia_siguiente_empieza_en_cero(tmp_path: Path) -> None:
    dia = Dia()
    diario = _diario(tmp_path, dia, usd=0.1)
    diario.sumar(0.5)
    assert diario.motivo_para_no_seguir() == TOPE_DIARIO_DINERO
    dia.hoy = date(2026, 11, 27)
    assert diario.motivo_para_no_seguir() is None
    assert diario.hoy == (0, 0.0)


def test_un_archivo_danado_empieza_en_cero(tmp_path: Path) -> None:
    (tmp_path / ARCHIVO_USO_DIARIO).write_text("{no es json", encoding="utf-8")
    assert _diario(tmp_path, Dia()).hoy == (0, 0.0)


# ---------- 3. Precios ----------


def test_precio_de_haiku_y_de_un_modelo_desconocido() -> None:
    uso = Uso(entrada=1_000_000, salida=1_000_000)
    assert costo_usd(uso, "claude-haiku-5-5") == pytest.approx(0.60)
    assert precio_conocido("claude-haiku-5-5-20261001")  # por el comienzo del nombre
    assert not precio_conocido("otro-modelo")
    # Un modelo desconocido NUNCA cuesta cero: se usa el precio de resguardo, alto.
    assert precio_de("otro-modelo") == PRECIO_DE_RESGUARDO
    assert costo_usd(uso, "otro-modelo") > costo_usd(uso, "claude-haiku-5-5")


# ---------- 4. Costo por caso ----------


def _costo(casos: list[str], usd: float) -> RegistroCosto:
    return RegistroCosto(
        ts=datetime(2026, 11, 26, tzinfo=UTC),
        sesion="s",
        casos=casos,
        modelo="claude-haiku-5-5",
        consultas=1,
        tokens_entrada=100,
        tokens_salida=20,
        tokens_cache_lectura=0,
        tokens_cache_escritura=0,
        usd=usd,
        precio_conocido=True,
    )


def test_costo_por_caso_reparte_y_ordena(tmp_path: Path) -> None:
    escribir_costo(tmp_path, _costo(["pa-logistica-istmo"], 0.004))
    escribir_costo(tmp_path, _costo(["pa-logistica-istmo", "ec-corp-andina"], 0.002))
    escribir_costo(tmp_path, _costo([], 0.001))
    with (tmp_path / "costos.jsonl").open("a", encoding="utf-8") as archivo:
        archivo.write("línea dañada\n")

    costos = {c.caso: c for c in costo_por_caso(tmp_path)}
    assert costos["pa-logistica-istmo"].usd == pytest.approx(0.005)
    assert costos["pa-logistica-istmo"].turnos == 2
    assert costos["ec-corp-andina"].usd == pytest.approx(0.001)
    assert costos[SIN_CASO].usd == pytest.approx(0.001)
    tabla = tabla_de_costos(costo_por_caso(tmp_path))
    assert tabla.splitlines()[2].startswith("| pa-logistica-istmo | 2 |")
    assert "**0.0070**" in tabla


def test_sin_costos_lo_dice(tmp_path: Path) -> None:
    assert "Todavía no hay costos" in tabla_de_costos(costo_por_caso(tmp_path))
