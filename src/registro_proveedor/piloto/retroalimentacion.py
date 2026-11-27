"""La opinión de quien prueba, respuesta por respuesta: 👍 / 👎 y un comentario (Paso 21).

Debajo de cada respuesta del chat hay dos botones. Lo que se marca queda en
`out/retroalimentacion.jsonl`: una línea por opinión, con QUÉ herramientas había pedido
el modelo en esa respuesta y para qué casos, así el reporte del piloto puede decir, por
ejemplo, "las respuestas sobre Constructora Andes recibieron 2 👎".

El comentario es texto libre: se enmascaran los datos sensibles por si alguien pega una
cuenta o una cédula (como en todos los logs), y se corta a 1000 caracteres.
"""

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from registro_proveedor.observabilidad import enmascarar_datos, obtener_logger

ARCHIVO_RETROALIMENTACION = "retroalimentacion.jsonl"
LARGO_MAXIMO_COMENTARIO = 1000


class Opinion(BaseModel):
    """Una línea de `out/retroalimentacion.jsonl`."""

    model_config = ConfigDict(frozen=True)

    ts: datetime
    sesion: str
    turno: int  # 0, 1, 2… en el orden de la conversación
    util: bool  # 👍 = True · 👎 = False
    comentario: str | None
    herramientas: list[str]  # las que pidió el modelo en esa respuesta, en orden
    casos: list[str]  # los casos que tocaron esas herramientas


def escribir_opinion(salida: Path, opinion: Opinion) -> None:
    """Agrega la opinión al archivo. Como la auditoría: si falla, no interrumpe."""
    destino = salida / ARCHIVO_RETROALIMENTACION
    linea = json.dumps(enmascarar_datos(opinion.model_dump(mode="json")), ensure_ascii=False)
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("a", encoding="utf-8", newline="\n") as archivo:
            archivo.write(linea + "\n")
    except OSError as e:
        obtener_logger().warning("no_se_pudo_escribir_opinion", archivo=str(destino), error=str(e))


def leer_opiniones(salida: Path) -> list[Opinion]:
    """Todas las opiniones guardadas. Una línea dañada se salta."""
    ruta = salida / ARCHIVO_RETROALIMENTACION
    if not ruta.exists():
        return []
    opiniones: list[Opinion] = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        try:
            opiniones.append(Opinion.model_validate_json(linea))
        except ValidationError:
            continue
    return opiniones
