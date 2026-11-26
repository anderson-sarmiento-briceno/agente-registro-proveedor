"""Topes de la demo abierta (Paso 18): por visitante y por día.

¿Por qué?
    La demo se publica SIN clave de acceso (decisión de Anderson, D65): la verá mucha
    gente. Sin topes, cualquiera podría gastar la clave de Anthropic sin límite. Los
    topes los pone el CÓDIGO; el modelo no puede saltárselos.

Dos tipos de tope:

1. Por visitante (`LimitadorPorVisitante`), según la dirección IP, EN MEMORIA:
       - conversaciones nuevas por hora (por defecto 5);
       - mensajes por minuto (por defecto 10; los clics en Aprobar también cuentan,
         porque también consultan al modelo).
   Se usa una "ventana deslizante": se guardan las horas de las últimas solicitudes y
   se cuentan las que caen dentro de la última hora (o minuto). Si el servidor se
   reinicia, se borra: no importa, son topes cortos.

2. Para todos juntos, por día (`UsoDiario`), guardado en `out/uso-diario.json`:
       - conversaciones nuevas por día (por defecto 100);
       - dólares por día (por defecto 2).
   Se guarda en un archivo para que reiniciar el servidor no lo ponga en cero. El día
   es el REAL (no `FECHA_EJECUCION`, que en una demo es fija y nunca cambiaría).

Cada revisión devuelve None si se puede seguir, o el mensaje para el visitante.
"""

import json
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ValidationError

from registro_proveedor.observabilidad import obtener_logger

ARCHIVO_USO_DIARIO = "uso-diario.json"
HORA = 3600.0
MINUTO = 60.0

DEMASIADAS_CONVERSACIONES = (
    "Abrió muchas conversaciones en poco tiempo. Espere un rato antes de empezar otra "
    "(puede seguir en la que ya tiene abierta)."
)
DEMASIADOS_MENSAJES = "Va muy rápido: espere un minuto antes de enviar otro mensaje."
TOPE_DIARIO_CONVERSACIONES = (
    "La demostración alcanzó su límite de conversaciones por hoy. Vuelva mañana."
)
TOPE_DIARIO_DINERO = "La demostración alcanzó su límite de uso por hoy. Vuelva mañana."


class LimitadorPorVisitante:
    """Ventanas deslizantes por dirección IP. Se puede usar desde varios hilos."""

    def __init__(
        self,
        *,
        conversaciones_por_hora: int,
        mensajes_por_minuto: int,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._conversaciones_por_hora = conversaciones_por_hora
        self._mensajes_por_minuto = mensajes_por_minuto
        self._reloj = reloj
        self._conversaciones: dict[str, deque[float]] = {}
        self._mensajes: dict[str, deque[float]] = {}
        self._candado = threading.Lock()

    def permitir_conversacion(self, visitante: str) -> str | None:
        with self._candado:
            if self._pasado(self._conversaciones, visitante, HORA, self._conversaciones_por_hora):
                return DEMASIADAS_CONVERSACIONES
            return None

    def permitir_mensaje(self, visitante: str) -> str | None:
        with self._candado:
            if self._pasado(self._mensajes, visitante, MINUTO, self._mensajes_por_minuto):
                return DEMASIADOS_MENSAJES
            return None

    def _pasado(
        self, registro: dict[str, deque[float]], visitante: str, ventana: float, tope: int
    ) -> bool:
        """¿Ya llegó al tope en la ventana? Si no, anota esta solicitud."""
        ahora = self._reloj()
        horas = registro.setdefault(visitante, deque())
        while horas and ahora - horas[0] >= ventana:
            horas.popleft()  # se salió de la ventana: ya no cuenta
        if len(horas) >= tope:
            return True
        horas.append(ahora)
        self._olvidar_inactivos(registro, ahora, ventana)
        return False

    @staticmethod
    def _olvidar_inactivos(registro: dict[str, deque[float]], ahora: float, ventana: float) -> None:
        """Borra a los visitantes sin solicitudes recientes, para no llenar la memoria."""
        for visitante in [v for v, h in registro.items() if not h or ahora - h[-1] >= ventana]:
            del registro[visitante]


class _Contadores(BaseModel):
    fecha: date
    conversaciones: int = 0
    usd: float = 0.0


class UsoDiario:
    """Cuántas conversaciones y cuántos dólares se usaron HOY, guardado en un archivo."""

    def __init__(
        self,
        carpeta: Path,
        *,
        tope_conversaciones: int,
        tope_usd: float,
        hoy: Callable[[], date] = date.today,
    ) -> None:
        self._archivo = carpeta / ARCHIVO_USO_DIARIO
        self._tope_conversaciones = tope_conversaciones
        self._tope_usd = tope_usd
        self._hoy = hoy
        self._candado = threading.Lock()
        self._contadores = self._leer()

    def motivo_para_no_abrir(self) -> str | None:
        """¿Se puede abrir una conversación nueva hoy?"""
        with self._candado:
            contadores = self._de_hoy()
            if contadores.conversaciones >= self._tope_conversaciones:
                return TOPE_DIARIO_CONVERSACIONES
            if contadores.usd >= self._tope_usd:
                return TOPE_DIARIO_DINERO
            return None

    def motivo_para_no_seguir(self) -> str | None:
        """¿Queda dinero hoy para otro mensaje?"""
        with self._candado:
            return TOPE_DIARIO_DINERO if self._de_hoy().usd >= self._tope_usd else None

    def contar_conversacion(self) -> None:
        with self._candado:
            contadores = self._de_hoy()
            contadores.conversaciones += 1
            self._guardar(contadores)

    def sumar(self, usd: float) -> None:
        with self._candado:
            contadores = self._de_hoy()
            contadores.usd += usd
            self._guardar(contadores)

    @property
    def hoy(self) -> tuple[int, float]:
        """(conversaciones, dólares) de hoy, para el monitoreo."""
        with self._candado:
            contadores = self._de_hoy()
            return contadores.conversaciones, contadores.usd

    def _de_hoy(self) -> _Contadores:
        """Los contadores de hoy; si cambió el día, empiezan en cero."""
        if self._contadores.fecha != self._hoy():
            self._contadores = _Contadores(fecha=self._hoy())
        return self._contadores

    def _leer(self) -> _Contadores:
        """Lee el archivo. Si no existe o está dañado, empieza en cero (y lo avisa)."""
        try:
            return _Contadores.model_validate_json(self._archivo.read_text(encoding="utf-8"))
        except FileNotFoundError:
            pass
        except (OSError, ValidationError) as e:
            obtener_logger().warning(
                "uso_diario_ilegible", archivo=str(self._archivo), error=str(e)[:200]
            )
        return _Contadores(fecha=self._hoy())

    def _guardar(self, contadores: _Contadores) -> None:
        """Escribe en un temporal y lo reemplaza de una vez, como el resto de out/."""
        try:
            self._archivo.parent.mkdir(parents=True, exist_ok=True)
            temporal = self._archivo.with_name(f".{self._archivo.name}.tmp")
            temporal.write_text(
                json.dumps(contadores.model_dump(mode="json")), encoding="utf-8", newline="\n"
            )
            os.replace(temporal, self._archivo)
        except OSError as e:
            obtener_logger().warning(
                "no_se_pudo_guardar_uso_diario", archivo=str(self._archivo), error=str(e)
            )
