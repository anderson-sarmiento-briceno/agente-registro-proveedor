"""Las herramientas reales del agente "Registro como Proveedor".

Cada herramienta es una envoltura delgada: valida sus argumentos (con su clase
`...Args`), llama a una función del dominio y devuelve un `Resultado`. La lógica de
negocio vive en `dominio/`, no aquí (principio 1).

`registro` es la lista de herramientas que verá el agente. Se llena sola al importar
este módulo, porque cada `@registro.herramienta(...)` registra su función.

Herramientas (se irán agregando paso a paso):
    Paso 4: proveedor_listar_casos, proveedor_leer_solicitud
    Paso 5: proveedor_mapear_campos, proveedor_confirmar_campo
    Paso 7: proveedor_generar_formulario
    Paso 8: proveedor_armar_paquete
    Paso 13: proveedor_simular_envio
"""

from pydantic import Field

from registro_proveedor.dominio import casos
from registro_proveedor.dominio.lectura import ErrorDeCaso
from registro_proveedor.herramientas.base import (
    ArgumentosHerramienta,
    Contexto,
    ErrorDeHerramienta,
    IdCasoArg,
    Registro,
    Resultado,
)

registro = Registro()

AYUDA_CASO = "Use proveedor_listar_casos para ver los casos disponibles."


# ---------- proveedor_listar_casos ----------


class ListarCasosArgs(ArgumentosHerramienta):
    filtro: str | None = Field(
        default=None,
        max_length=100,
        description="Opcional. Una o dos palabras del cliente o del país para filtrar, "
        "por ejemplo «Ecuador», «EC» o «andina». Sin filtro, lista todos.",
    )


def _resumir_listado(listado: casos.ListadoCasos) -> str:
    texto = f"{len(listado.casos)} casos"
    if listado.filtro:
        texto += f" con el filtro «{listado.filtro}»"
    if listado.casos_con_error:
        texto += f"; {len(listado.casos_con_error)} con error"
    return texto


@registro.herramienta(
    nombre="proveedor_listar_casos",
    descripcion="Lista los casos de registro disponibles (cliente, país, formato y fecha), "
    "con un filtro opcional por cliente o país, para identificar de qué caso se habla.",
    argumentos=ListarCasosArgs,
    resumir=_resumir_listado,
)
def listar_casos(args: ListarCasosArgs, ctx: Contexto) -> Resultado[casos.ListadoCasos]:
    return Resultado(ok=True, data=casos.listar_casos(ctx.datos, args.filtro))


# ---------- proveedor_leer_solicitud ----------


class LeerSolicitudArgs(ArgumentosHerramienta):
    caso: IdCasoArg


def _resumir_lectura(caso: casos.CasoLeido) -> str:
    return (
        f"{caso.pais} · {caso.formato} · {len(caso.campos)} campos · "
        f"{len(caso.soportes)} soportes exigidos"
    )


@registro.herramienta(
    nombre="proveedor_leer_solicitud",
    descripcion="Lee la solicitud y la plantilla de un caso y devuelve el país, el cliente, "
    "el formato, los campos que pide y los soportes que exige.",
    argumentos=LeerSolicitudArgs,
    resumir=_resumir_lectura,
)
def leer_solicitud(args: LeerSolicitudArgs, ctx: Contexto) -> Resultado[casos.CasoLeido]:
    try:
        return Resultado(ok=True, data=casos.leer_caso(ctx.datos, args.caso))
    except ErrorDeCaso as e:
        # Se agrega una ayuda para que el agente sepa cómo seguir. Los demás errores de
        # datos (plantilla corrupta, etc.) los convierte el decorador en ok=False.
        raise ErrorDeHerramienta(f"{'; '.join(e.problemas)}. {AYUDA_CASO}") from None
