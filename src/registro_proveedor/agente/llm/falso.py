"""Un modelo de lenguaje FALSO, con guion, para probar el agente sin clave ni costo.

Se le da una lista de respuestas (el "guion") y las devuelve una por una, en orden. Si
un elemento del guion es un `ErrorDelModelo`, lo lanza (así se prueba qué hace el agente
cuando el proveedor falla). Además guarda todo lo que recibió, para revisar en las
pruebas qué se le envió al modelo.

Ejemplo:
    falso = AdaptadorFalso([
        pide("proveedor_listar_casos", {"filtro": "Ecuador"}),
        responde("Encontré el caso ec-corp-andina."),
    ])
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from registro_proveedor.agente.llm.adaptador import (
    AdaptadorLLM,
    BloqueTexto,
    DefinicionHerramienta,
    ErrorDelModelo,
    LlamadaHerramienta,
    Mensaje,
    MotivoFin,
    RespuestaModelo,
    Uso,
)

MODELO_FALSO = "modelo-falso"


@dataclass(frozen=True)
class Envio:
    """Lo que el agente le mandó al modelo falso en una llamada."""

    sistema: str
    mensajes: tuple[Mensaje, ...]
    herramientas: tuple[DefinicionHerramienta, ...]


@dataclass
class AdaptadorFalso:
    guion: list[RespuestaModelo | ErrorDelModelo]
    envios: list[Envio] = field(default_factory=list)

    @property
    def modelo(self) -> str:
        return MODELO_FALSO

    def enviar(
        self,
        sistema: str,
        mensajes: Sequence[Mensaje],
        herramientas: Sequence[DefinicionHerramienta],
    ) -> RespuestaModelo:
        self.envios.append(Envio(sistema, tuple(mensajes), tuple(herramientas)))
        if not self.guion:
            raise AssertionError("el modelo falso se quedó sin respuestas en su guion")
        siguiente = self.guion.pop(0)
        if isinstance(siguiente, ErrorDelModelo):
            raise siguiente
        return siguiente


# ---------- Atajos para escribir guiones ----------

_contador = 0


def pide(
    nombre: str, argumentos: dict[str, Any], *, id_llamada: str | None = None
) -> RespuestaModelo:
    """Una respuesta en la que el modelo pide UNA herramienta."""
    return pide_varias([(nombre, argumentos, id_llamada)])


def pide_varias(llamadas: list[tuple[str, dict[str, Any], str | None]]) -> RespuestaModelo:
    """Una respuesta en la que el modelo pide varias herramientas a la vez."""
    global _contador
    bloques: list[LlamadaHerramienta] = []
    for nombre, argumentos, id_llamada in llamadas:
        _contador += 1
        bloques.append(
            LlamadaHerramienta(
                id=id_llamada or f"llamada-{_contador}", nombre=nombre, argumentos=argumentos
            )
        )
    return RespuestaModelo(
        bloques=list(bloques), motivo=MotivoFin.PIDE_HERRAMIENTA, uso=Uso(), modelo=MODELO_FALSO
    )


def responde(texto: str, motivo: MotivoFin = MotivoFin.TERMINO) -> RespuestaModelo:
    """Una respuesta de solo texto (por ejemplo, el resumen final para la analista)."""
    return RespuestaModelo(
        bloques=[BloqueTexto(texto=texto)], motivo=motivo, uso=Uso(), modelo=MODELO_FALSO
    )


def _cumple_el_contrato(adaptador: AdaptadorFalso) -> AdaptadorLLM:
    """Para que mypy compruebe que el modelo falso cumple `AdaptadorLLM`."""
    return adaptador
