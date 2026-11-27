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
    Paso 13: proveedor_registrar_envio (antes proveedor_simular_envio)
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from registro_proveedor.dominio import casos, envio, mapeo, paquete
from registro_proveedor.dominio.generadores import generar_formulario as generar
from registro_proveedor.dominio.generadores.comun import (
    ErrorDeGeneracion,
    FormularioGenerado,
    verificar_correspondencia,
)
from registro_proveedor.dominio.lectura import (
    CARPETA_SOPORTES,
    ErrorDeCaso,
    ErrorDeDatos,
    cargar_glosario,
    cargar_indice_soportes,
    cargar_maestro,
    cargar_solicitud,
    carpeta_de_caso,
)
from registro_proveedor.dominio.modelos import NOMBRES_SOPORTE, Formato
from registro_proveedor.dominio.reglas import EvaluacionSoporte, cargar_reglas
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
    texto = _n(len(listado.casos), "caso", "casos")
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
        archivo=ctx.ruta_en_salida(resultado.caso, mapeo.ARCHIVO_MAPEO),
        version_maestro=resultado.version_maestro or "sin versión",
        llenos=grupo(mapeo.Estado.LLENO),
        faltantes=grupo(mapeo.Estado.FALTANTE),
        requiere_confirmacion=grupo(mapeo.Estado.REQUIERE_CONFIRMACION),
        avisos=avisos,
    )


def _n(cantidad: int, singular: str, plural: str) -> str:
    """La cantidad con la palabra en singular o plural: "1 faltante", "2 faltantes"."""
    return f"{cantidad} {singular if cantidad == 1 else plural}"


def _contar(vista: VistaMapeo) -> str:
    return (
        f"{_n(len(vista.llenos), 'lleno', 'llenos')} · "
        f"{_n(len(vista.faltantes), 'faltante', 'faltantes')} · "
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
    "aceptar el valor propuesto o dejarlo faltante. Requiere aprobación de la analista: "
    "al pedirla, queda pendiente hasta que ella la apruebe.",
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


# ---------- proveedor_generar_formulario ----------


class GenerarFormularioArgs(ArgumentosHerramienta):
    caso: IdCasoArg


class VistaFormulario(_Vista):
    """Lo que ve el modelo después de generar: dónde quedó el archivo y los conteos.

    No incluye ningún valor: el modelo no los necesita para explicar el resultado.
    """

    caso: str
    formato: str
    formato_nombre: str  # para personas: "Excel (se genera formulario.xlsx)"
    archivo: str
    escritos: int
    faltantes: int
    pendientes: int
    avisos: list[str]


AVISO_PORTAL = (
    "formato no soportado para automatizar: el cliente usa un portal web; "
    "se generaron los valores listos para copiar"
)


def _resumir_formulario(v: VistaFormulario) -> str:
    return (
        f"{v.archivo} · {_n(v.escritos, 'escrito', 'escritos')} · "
        f"{_n(v.faltantes, 'faltante', 'faltantes')} · "
        f"{_n(v.pendientes, 'pendiente', 'pendientes')}"
    )


@registro.herramienta(
    nombre="proveedor_generar_formulario",
    descripcion="Genera el formulario del caso en el formato del cliente (Excel, PDF o valores "
    "para copiar en el portal) a partir del mapeo guardado; no recibe valores.",
    argumentos=GenerarFormularioArgs,
    resumir=_resumir_formulario,
)
def generar_formulario(args: GenerarFormularioArgs, ctx: Contexto) -> Resultado[VistaFormulario]:
    caso = _leer_caso(ctx, args.caso)
    carpeta = ctx.carpeta_de_salida(args.caso)
    guardado = _mapeo_guardado(carpeta, args.caso)
    try:
        verificar_correspondencia(guardado, caso)
        generado = generar(guardado, caso, carpeta)
    except ErrorDeGeneracion as e:
        raise ErrorDeHerramienta(str(e)) from None
    return Resultado(ok=True, data=_vista_formulario(ctx, caso, generado))


def _mapeo_guardado(carpeta: Path, caso: str) -> mapeo.Mapeo:
    """El mapeo de `out/<caso>/mapeo.json`; si no existe o no sirve, un error que dice qué hacer.

    Un mapeo.json de antes del Paso 7 no tiene `celda_etiqueta` y no pasa la validación:
    por eso el mensaje sugiere volver a mapear.
    """
    try:
        guardado = mapeo.cargar_mapeo(carpeta)
    except ErrorDeDatos:
        raise ErrorDeHerramienta(
            f"el mapeo guardado del caso «{caso}» está dañado o es de una versión anterior: "
            "vuelva a usar proveedor_mapear_campos"
        ) from None
    if guardado is None:
        raise ErrorDeHerramienta(
            f"el caso «{caso}» todavía no tiene mapeo: primero use proveedor_mapear_campos"
        )
    return guardado


def _vista_formulario(
    ctx: Contexto, caso: casos.CasoLeido, generado: FormularioGenerado
) -> VistaFormulario:
    avisos: list[str] = []
    if caso.formato is Formato.PORTAL:
        avisos.append(AVISO_PORTAL)
    if generado.pendientes:
        cuantos = (
            "hay 1 campo por confirmar: quedó vacío"
            if generado.pendientes == 1
            else f"hay {generado.pendientes} campos por confirmar: quedaron vacíos"
        )
        avisos.append(f"{cuantos} en el formulario; después de confirmar, vuelva a generarlo")
    return VistaFormulario(
        caso=caso.caso,
        formato=caso.formato,
        formato_nombre=caso.formato_nombre,
        archivo=ctx.ruta_en_salida(caso.caso, generado.ruta.name),
        escritos=generado.escritos,
        faltantes=generado.faltantes,
        pendientes=generado.pendientes,
        avisos=avisos,
    )


# ---------- proveedor_armar_paquete ----------


class ArmarPaqueteArgs(ArgumentosHerramienta):
    caso: IdCasoArg


class SoporteVisto(_Vista):
    """Una fila del checklist de soportes, lista para mostrar (Paso 16).

    Trae el nombre, el estado y "qué hacer" ya escritos para personas, los mismos del
    checklist.md: el modelo los copia en su tabla en vez de traducir códigos.
    """

    tipo: str
    nombre: str  # "Cámara de Comercio"
    estado: str  # código: presente, por_vencer, vencido, ausente
    estado_texto: str  # "⚠️ por vencer"
    vence: str  # "2027-02-24 (faltan 90 días)" o "—"
    que_hacer: str  # "Pedir la renovación pronto (no bloquea la firma)"
    nota: str


class VistaPaquete(_Vista):
    """Lo que ve el modelo del paquete: si está listo, por qué no, y qué hay dentro.

    Sin valores de los campos: no los necesita para explicar el resultado.
    """

    caso: str
    carpeta: str
    formato_nombre: str
    listo_para_firma: bool
    motivos: list[str]
    avisos: list[str]
    soportes: list[SoporteVisto]
    archivos: list[str]


def _soporte_visto(e: EvaluacionSoporte) -> SoporteVisto:
    return SoporteVisto(
        tipo=e.tipo,
        nombre=NOMBRES_SOPORTE[e.tipo],
        estado=e.estado,
        estado_texto=paquete.TEXTO_SOPORTE[e.estado],
        vence=paquete.vence(e),
        que_hacer=paquete.QUE_HACER[e.estado],
        nota=e.nota,
    )


def _resumir_paquete(v: VistaPaquete) -> str:
    if v.listo_para_firma:
        return f"{v.carpeta} · listo para firma"
    return f"{v.carpeta} · NO listo: {_n(len(v.motivos), 'motivo', 'motivos')}"


@registro.herramienta(
    nombre="proveedor_armar_paquete",
    descripcion="Arma el paquete para firma del caso (formulario, soportes, checklist, borrador "
    "de correo y manifiesto) y dice si está listo para firma y, si no, por qué.",
    argumentos=ArmarPaqueteArgs,
    resumir=_resumir_paquete,
)
def armar_paquete(args: ArmarPaqueteArgs, ctx: Contexto) -> Resultado[VistaPaquete]:
    caso = _leer_caso(ctx, args.caso)
    carpeta = ctx.carpeta_de_salida(args.caso)
    try:
        armado = paquete.armar_paquete(
            caso=caso,
            solicitud=cargar_solicitud(carpeta_de_caso(ctx.datos, args.caso)),
            mapeo=_mapeo_guardado(carpeta, args.caso),
            maestro=cargar_maestro(ctx.datos),
            indice=cargar_indice_soportes(ctx.datos),
            carpeta_soportes=ctx.datos / CARPETA_SOPORTES,
            reglas=cargar_reglas(ctx.reglas),
            fecha=ctx.fecha_ejecucion,
            generado_en=ctx.reloj(),
            carpeta_caso=carpeta,
        )
    except (ErrorDeGeneracion, paquete.ErrorDePaquete) as e:
        raise ErrorDeHerramienta(str(e)) from None
    return Resultado(
        ok=True,
        data=VistaPaquete(
            caso=caso.caso,
            carpeta=ctx.ruta_en_salida(caso.caso, paquete.CARPETA_PAQUETE),
            listo_para_firma=armado.listo_para_firma,
            motivos=armado.motivos,
            avisos=armado.avisos,
            formato_nombre=caso.formato_nombre,
            soportes=[_soporte_visto(s) for s in armado.soportes],
            archivos=armado.archivos,
        ),
    )


# ---------- proveedor_registrar_envio ----------
# Antes se llamaba `proveedor_simular_envio`. Se renombró para la demo (Paso 16):
# "registrar" dice exactamente lo que hace (deja la constancia), sin repetir
# "simulación" en cada respuesta. La constancia aclara UNA vez que es modo piloto.


class RegistrarEnvioArgs(ArgumentosHerramienta):
    caso: IdCasoArg


class VistaEnvio(_Vista):
    caso: str
    archivo: str
    archivos_enviados: int
    aprobacion: str


def _resumir_envio(v: VistaEnvio) -> str:
    return (
        f"{v.archivo} · {_n(v.archivos_enviados, 'archivo', 'archivos')} · "
        f"aprobación {v.aprobacion}"
    )


@registro.herramienta(
    nombre="proveedor_registrar_envio",
    descripcion="Registra el envío del paquete para firma del caso en la constancia "
    "constancia-envio.md. En modo piloto no envía nada al cliente: la entrega la hace la "
    "analista fuera del sistema. Solo si el paquete está listo y al día. Requiere "
    "aprobación de la analista.",
    argumentos=RegistrarEnvioArgs,
    requiere_confirmacion=True,
    resumir=_resumir_envio,
)
def registrar_envio(args: RegistrarEnvioArgs, ctx: Contexto) -> Resultado[VistaEnvio]:
    # El doble candado de `base.py` ya comprobó que hay una aprobación válida; aquí
    # solo se usa para anotar quién aprobó y cuándo.
    aprobacion = ctx.aprobacion
    if aprobacion is None:  # no debería pasar: el candado lo impide antes
        raise ErrorDeHerramienta("el envío requiere la aprobación de la analista")
    caso = _leer_caso(ctx, args.caso)
    carpeta = ctx.carpeta_de_salida(args.caso)
    try:
        enviado = envio.registrar_envio(
            caso=caso,
            solicitud=cargar_solicitud(carpeta_de_caso(ctx.datos, args.caso)),
            mapeo=_mapeo_guardado(carpeta, args.caso),
            carpeta_caso=carpeta,
            fecha=ctx.fecha_ejecucion,
            aprobacion=aprobacion.id,
            aprobado_por=aprobacion.por,
            aprobado_en=aprobacion.en,
        )
    except envio.ErrorDeEnvio as e:
        raise ErrorDeHerramienta(str(e)) from None
    return Resultado(
        ok=True,
        data=VistaEnvio(
            caso=caso.caso,
            archivo=ctx.ruta_en_salida(caso.caso, enviado.ruta.name),
            archivos_enviados=len(enviado.archivos),
            aprobacion=aprobacion.id,
        ),
    )
