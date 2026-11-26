"""Las sesiones de la API, en memoria (Paso 15).

Cada conversación del navegador es una `Sesion` del ciclo (historial, tokens,
confirmaciones pendientes) más lo que la API necesita para mostrarla:
    - `turnos`: el historial TAL COMO LO VIO la analista (respuestas ya revisadas);
    - `candado`: para que dos mensajes a la vez a la MISMA conversación no mezclen su
      historial. Si llega uno mientras otro se procesa, se rechaza con un mensaje claro;
    - `ultimo_uso`: para vencer las sesiones abandonadas.

Límites, para no llenar la memoria del servidor:
    - una sesión vence tras 2 horas sin uso;
    - hay un máximo de sesiones abiertas (100). Si se llega, primero se borran las
      vencidas; si siguen siendo demasiadas, la sesión nueva se rechaza (no se borra
      una conversación activa de otra persona).

Qué se pierde: todo, si el servidor se reinicia (los archivos de `out/` quedan). Guardar
las sesiones fuera de la memoria es parte del despliegue (Paso 19).
"""

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from registro_proveedor.agente.ciclo import Sesion
from registro_proveedor.api.esquemas import TurnRecord

MAXIMO_DE_SESIONES = 100
INACTIVIDAD_MAXIMA = timedelta(hours=2)


def _ahora() -> datetime:
    return datetime.now(UTC)


class DemasiadasSesiones(Exception):
    """No caben más sesiones abiertas."""


@dataclass
class SesionApi:
    sesion: Sesion
    creada_en: datetime
    ultimo_uso: datetime
    turnos: list[TurnRecord] = field(default_factory=list)
    candado: threading.Lock = field(default_factory=threading.Lock)

    @property
    def id(self) -> str:
        return self.sesion.id


class AlmacenDeSesiones:
    """Las sesiones abiertas, por id. Se puede usar desde varios hilos a la vez."""

    def __init__(
        self,
        crear_sesion: Callable[[str], Sesion],
        *,
        maximo: int = MAXIMO_DE_SESIONES,
        inactividad: timedelta = INACTIVIDAD_MAXIMA,
        reloj: Callable[[], datetime] = _ahora,
    ) -> None:
        self._crear_sesion = crear_sesion
        self._maximo = maximo
        self._inactividad = inactividad
        self._reloj = reloj
        self._sesiones: dict[str, SesionApi] = {}
        # Un candado para el diccionario: FastAPI atiende las solicitudes en varios
        # hilos, y dos podrían crear o borrar sesiones al mismo tiempo.
        self._candado = threading.Lock()

    def nueva(self) -> SesionApi:
        """Crea una sesión con un id imposible de adivinar. Lanza `DemasiadasSesiones`."""
        with self._candado:
            self._borrar_vencidas()
            if len(self._sesiones) >= self._maximo:
                raise DemasiadasSesiones
            ahora = self._reloj()
            nueva = SesionApi(
                sesion=self._crear_sesion(uuid.uuid4().hex), creada_en=ahora, ultimo_uso=ahora
            )
            self._sesiones[nueva.id] = nueva
            return nueva

    def obtener(self, sesion_id: str) -> SesionApi | None:
        """La sesión, si existe y no ha vencido (y anota que se usó). Si no, None."""
        with self._candado:
            encontrada = self._sesiones.get(sesion_id)
            if encontrada is None:
                return None
            if self._vencida(encontrada):
                del self._sesiones[sesion_id]
                return None
            encontrada.ultimo_uso = self._reloj()
            return encontrada

    def __len__(self) -> int:
        return len(self._sesiones)

    def _vencida(self, sesion: SesionApi) -> bool:
        return self._reloj() - sesion.ultimo_uso > self._inactividad

    def _borrar_vencidas(self) -> None:
        for sesion_id in [i for i, s in self._sesiones.items() if self._vencida(s)]:
            del self._sesiones[sesion_id]
