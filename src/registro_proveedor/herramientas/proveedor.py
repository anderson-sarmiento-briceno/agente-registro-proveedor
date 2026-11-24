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

from pydantic import BaseModel, ConfigDict, Field

from registro_proveedor.dominio import casos, mapeo
from registro_proveedor.dominio.lectura import (
    ErrorDeCaso,
    ErrorDeDatos,
    cargar_glosario,
    cargar_maestro,
)
from registro_proveedor.dominio.reglas import cargar_reglas
from registro_proveedor.herramientas.base import (
    ArgumentosHerramienta,
    Contexto,
    ErrorDeHerramienta,
    IdCasoArg,
    Registro,
    Resultado,
)
from registro_proveedor.observabilidad import enmascarar, es_ruta_sensible

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
    return Resultado(ok=True, data=_leer_caso(ctx, args.caso))


def _leer_caso(ctx: Contexto, caso: str) -> casos.CasoLeido:
    """Lee el caso; si no existe, agrega una ayuda para que el agente sepa cómo seguir.

    Los demás errores de datos (plantilla corrupta, etc.) los convierte el decorador
    en ok=False con su mensaje.
    """
    try:
        return casos.leer_caso(ctx.datos, caso)
    except ErrorDeCaso as e:
        raise ErrorDeHerramienta(f"{'; '.join(e.problemas)}. {AYUDA_CASO}") from None


# ---------- Lo que ve el modelo de un mapeo (con lo sensible enmascarado) ----------


class _Vista(BaseModel):
    model_config = ConfigDict(frozen=True)


class VistaMapeo(_Vista):
    """El mapeo tal como se le muestra al modelo: agrupado por estado y enmascarado.

    El mapeo completo, con los valores reales, queda solo en `archivo` (mapeo.json).
    """

    caso: str
    archivo: str
    version_maestro: str
    llenos: list[mapeo.CampoMapeado]
    faltantes: list[mapeo.CampoMapeado]
    requiere_confirmacion: list[mapeo.CampoMapeado]
    avisos: list[str]


def _para_mostrar(campo: mapeo.CampoMapeado) -> mapeo.CampoMapeado:
    """Copia del campo con el valor enmascarado si es un dato sensible (RN8).

    Aquí no sirve el enmascaramiento por nombre de campo de `a_json()`: el número de
    cuenta viene en un campo llamado `valor`. Por eso se mira la RUTA del maestro.
    También se enmascara el valor propuesto guardado en la confirmación.
    """
    if campo.ruta is None or not es_ruta_sensible(campo.ruta):
        return campo
    cambios: dict[str, object] = {}
    if campo.valor is not None:
        cambios["valor"] = enmascarar(campo.valor)
    if campo.confirmacion is not None:
        cambios["confirmacion"] = campo.confirmacion.model_copy(
            update={"valor_propuesto": enmascarar(campo.confirmacion.valor_propuesto)}
        )
    return campo.model_copy(update=cambios)


def _vista(ctx: Contexto, resultado: mapeo.Mapeo, avisos: list[str]) -> VistaMapeo:
    def grupo(estado: mapeo.Estado) -> list[mapeo.CampoMapeado]:
        return [_para_mostrar(c) for c in resultado.en_estado(estado)]

    return VistaMapeo(
        caso=resultado.caso,
        archivo=f"{ctx.salida.name}/{resultado.caso}/{mapeo.ARCHIVO_MAPEO}",
        version_maestro=resultado.version_maestro or "sin versión",
        llenos=grupo(mapeo.Estado.LLENO),
        faltantes=grupo(mapeo.Estado.FALTANTE),
        requiere_confirmacion=grupo(mapeo.Estado.REQUIERE_CONFIRMACION),
        avisos=avisos,
    )


def _contar(vista: VistaMapeo) -> str:
    return (
        f"{len(vista.llenos)} llenos · {len(vista.faltantes)} faltantes · "
        f"{len(vista.requiere_confirmacion)} por confirmar"
    )


# ---------- proveedor_mapear_campos ----------


class MapearCamposArgs(ArgumentosHerramienta):
    caso: IdCasoArg


@registro.herramienta(
    nombre="proveedor_mapear_campos",
    descripcion="Cruza cada campo del caso con el repositorio maestro y lo clasifica en "
    "lleno, faltante o requiere_confirmacion, con su origen; guarda el mapeo del caso.",
    argumentos=MapearCamposArgs,
    resumir=_contar,
)
def mapear_campos(args: MapearCamposArgs, ctx: Contexto) -> Resultado[VistaMapeo]:
    caso = _leer_caso(ctx, args.caso)
    carpeta = ctx.carpeta_de_salida(args.caso)
    avisos: list[str] = []
    try:
        anterior = mapeo.cargar_mapeo(carpeta)
    except ErrorDeDatos:
        # Un mapeo anterior dañado no impide mapear de nuevo; solo se pierden sus
        # confirmaciones, y se avisa para que la analista lo sepa.
        anterior = None
        avisos.append("el mapeo anterior estaba dañado: no se conservaron sus confirmaciones")
    resultado = mapeo.mapear_caso(
        caso,
        cargar_glosario(ctx.datos),
        cargar_maestro(ctx.datos),
        # Las reglas se leen en cada llamada: si alguien edita reglas.yaml, el cambio se
        # nota en el siguiente mapeo, sin reiniciar nada.
        cargar_reglas(ctx.reglas),
        generado_en=ctx.reloj(),
        fecha_ejecucion=ctx.fecha_ejecucion,
        anterior=anterior,
    )
    mapeo.guardar_mapeo(carpeta, resultado)
    return Resultado(ok=True, data=_vista(ctx, resultado, avisos))


# ---------- proveedor_confirmar_campo ----------


class ConfirmarCampoArgs(ArgumentosHerramienta):
    caso: IdCasoArg
    etiqueta: str = Field(
        min_length=1,
        max_length=200,
        description="La etiqueta del campo tal como aparece en el mapeo, "
        "por ejemplo «Número de cuenta».",
    )
    decision: mapeo.Decision = Field(
        description="«aceptar» para usar el valor propuesto, o «dejar_faltante» para dejarlo vacío."
    )


class ResultadoConfirmacion(_Vista):
    campo: mapeo.CampoMapeado
    resumen: str


def _resumir_confirmacion(r: ResultadoConfirmacion) -> str:
    return f"«{r.campo.etiqueta}» → {r.campo.estado}"


@registro.herramienta(
    nombre="proveedor_confirmar_campo",
    descripcion="Resuelve un campo en requiere_confirmacion del mapeo de un caso: "
    "aceptar el valor propuesto o dejarlo faltante. Requiere aprobación de la analista.",
    argumentos=ConfirmarCampoArgs,
    requiere_confirmacion=True,
    resumir=_resumir_confirmacion,
)
def confirmar_campo(args: ConfirmarCampoArgs, ctx: Contexto) -> Resultado[ResultadoConfirmacion]:
    carpeta = ctx.carpeta_de_salida(args.caso)
    actual = mapeo.cargar_mapeo(carpeta)
    if actual is None:
        raise ErrorDeHerramienta(
            f"el caso «{args.caso}» todavía no tiene mapeo: primero use proveedor_mapear_campos"
        )
    try:
        nuevo, campo = mapeo.confirmar_campo(
            actual, args.etiqueta, args.decision, por=ctx.usuario, en=ctx.reloj()
        )
    except mapeo.ErrorDeMapeo as e:
        raise ErrorDeHerramienta(str(e)) from None
    mapeo.guardar_mapeo(carpeta, nuevo)
    vista = _vista(ctx, nuevo, [])
    return Resultado(
        ok=True, data=ResultadoConfirmacion(campo=_para_mostrar(campo), resumen=_contar(vista))
    )
