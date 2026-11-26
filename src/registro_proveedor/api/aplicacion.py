"""La API HTTP del agente, con FastAPI (Paso 15). Solo transporte: no tiene lógica propia.

Cada endpoint traduce HTTP a una de las dos entradas del ciclo y vuelta:

    POST /api/chat                 → Agente.responder(sesion, mensaje)
    POST /api/confirmations/{id}   → Agente.resolver(sesion, id, aprobar=...)
    GET  /api/sessions/{id}        → el historial tal como lo vio la analista
    GET  /api/health               → ¿está vivo? ¿hay modelo configurado? (sin la clave)
    GET  /                         → el front de chat (`web/`, Paso 16)

La documentación se genera sola en `/docs` (OpenAPI).

Cómo se levanta:
    uv run uvicorn registro_proveedor.api.app:app --reload
(`app.py` solo crea la app con la configuración de `.env`; todo lo demás está aquí.)

`crear_app` arma todo una sola vez (instrucciones, adaptador, agente, sesiones). Las
pruebas la llaman con un modelo falso y una carpeta `out/` temporal. Por eso está en
este archivo y no en `app.py`: importarla no arma la app real.

Seguridad (el "hecho cuando" del paso):
    - Ninguna respuesta lleva la clave ni el historial crudo: todo sale de `Turno`
      (respuestas revisadas, argumentos enmascarados), ver `esquemas.py`.
    - Los errores se explican en español, sin traza técnica. Un error inesperado
      responde 500 con un mensaje corto; el detalle va al log de operación.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from registro_proveedor.agente.ciclo import Agente, Sesion, Turno
from registro_proveedor.agente.instrucciones import cargar_instrucciones
from registro_proveedor.agente.llm.adaptador import AdaptadorLLM
from registro_proveedor.agente.llm.costos import costo_usd
from registro_proveedor.agente.llm.proveedor_anthropic import AdaptadorAnthropic
from registro_proveedor.api.esquemas import (
    PATRON_CONFIRMACION,
    PATRON_SESION,
    ChatRequest,
    ChatResponse,
    ConfirmationRequest,
    ErrorResponse,
    HealthResponse,
    PortalField,
    PortalValuesResponse,
    SessionResponse,
    TurnRecord,
    de_confirmacion,
    de_turno,
    de_uso,
)
from registro_proveedor.api.limites import LimitadorPorVisitante, UsoDiario
from registro_proveedor.api.sesiones import AlmacenDeSesiones, DemasiadasSesiones, SesionApi
from registro_proveedor.config import RAIZ_PROYECTO, Configuracion, cargar_configuracion
from registro_proveedor.dominio.casos import leer_caso
from registro_proveedor.dominio.generadores.portal import valores_para_copiar
from registro_proveedor.dominio.lectura import ErrorDeDatos, describir_error_validacion
from registro_proveedor.dominio.mapeo import cargar_mapeo
from registro_proveedor.dominio.modelos import PATRON_ID_CASO, Formato
from registro_proveedor.herramientas.base import Contexto
from registro_proveedor.herramientas.proveedor import registro
from registro_proveedor.observabilidad import RegistroLlamada, escribir_auditoria, obtener_logger

PROVEEDOR = "anthropic"

# Paso 16 · El front: HTML + JS simple, sin librerías externas.
CARPETA_WEB = RAIZ_PROYECTO / "web"
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
RUTAS_SIN_CSP = ("/docs", "/redoc", "/openapi.json")

SIN_MODELO = (
    "El modelo no está configurado: falta ANTHROPIC_API_KEY en el archivo .env del "
    "servidor. El núcleo sigue funcionando sin modelo (scripts/demo.py)."
)
SESION_NO_EXISTE = (
    "No existe esa conversación, o venció por inactividad. Empiece una nueva enviando "
    "un mensaje sin session_id."
)
OCUPADA = "La conversación todavía está procesando el mensaje anterior. Espere la respuesta."
DEMASIADAS = "Hay demasiadas conversaciones abiertas en el servidor. Intente más tarde."
CASO_NO_EXISTE = "No existe ese caso."
NO_ES_PORTAL = "Ese caso no se llena en un portal web: su formulario es un archivo (Excel o PDF)."
SIN_MAPEO = "Todavía no hay valores para ese caso: primero pídale al agente que lo prepare."
NOTA_PORTAL = (
    "Los datos sensibles (cuenta bancaria, identificación) se muestran enmascarados en "
    "esta página. Sus valores completos están en el archivo valores-portal.md del caso."
)

# Paso 18 · El conteo diario de la demo vive junto a los demás archivos generados.
CARPETA_SALIDA = RAIZ_PROYECTO / "out"

# Las respuestas de error, para la documentación de cada endpoint.
ERRORES: dict[int | str, dict[str, object]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
}


def crear_app(
    config: Configuracion | None = None,
    *,
    adaptador: AdaptadorLLM | None = None,
    crear_contexto: Callable[[str], Contexto] | None = None,
    almacen: AlmacenDeSesiones | None = None,
    limitador: LimitadorPorVisitante | None = None,
    uso_diario: UsoDiario | None = None,
) -> FastAPI:
    """Arma la aplicación. Sin argumentos, usa la configuración de `.env`.

    - `adaptador`: el modelo. Por defecto, Anthropic con la clave de `.env`; las pruebas
      pasan un modelo falso.
    - `crear_contexto`: cómo se arma el contexto de una sesión nueva a partir de su id.
      Por defecto, `datos/` y `out/` del proyecto; las pruebas usan un `out/` temporal.
    - `almacen`: dónde viven las sesiones; las pruebas lo pasan para controlar el reloj.
    - `limitador` y `uso_diario` (Paso 18): los topes por visitante y por día. Por
      defecto, los de `.env`, con el conteo diario en `out/uso-diario.json`.
    """
    config = config or cargar_configuracion()
    instrucciones = cargar_instrucciones()  # si falta el prompt, mejor no arrancar
    modelo_configurado = adaptador is not None or config.hay_clave_llm()
    modelo = adaptador or AdaptadorAnthropic.desde_configuracion(config)
    agente = Agente.desde_configuracion(
        config, adaptador=modelo, registro=registro, instrucciones=instrucciones
    )

    def sesion_nueva(sesion_id: str) -> Sesion:
        if crear_contexto is not None:
            return Sesion(crear_contexto(sesion_id))
        return Sesion.nueva(config, sesion_id=sesion_id)

    # `is None` y no `or`: un almacén vacío tiene largo 0 y Python lo trataría como "falso".
    sesiones = almacen if almacen is not None else AlmacenDeSesiones(sesion_nueva)
    por_visitante = limitador or LimitadorPorVisitante(
        conversaciones_por_hora=config.tope_conversaciones_hora_ip,
        mensajes_por_minuto=config.tope_mensajes_minuto_ip,
    )
    diario = uso_diario or UsoDiario(
        CARPETA_SALIDA,
        tope_conversaciones=config.tope_conversaciones_dia,
        tope_usd=config.tope_usd_dia,
    )

    def revisar_topes(solicitud: Request, *, conversacion_nueva: bool) -> None:
        """Paso 18 · Antes de gastar: los topes por visitante y por día. 429 si no se puede."""
        visitante = solicitud.client.host if solicitud.client else "desconocido"
        motivo = por_visitante.permitir_mensaje(visitante) or diario.motivo_para_no_seguir()
        if motivo is None and conversacion_nueva:
            motivo = diario.motivo_para_no_abrir() or por_visitante.permitir_conversacion(visitante)
        if motivo is not None:
            obtener_logger().warning("tope_de_la_demo", motivo=motivo)
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, motivo)

    def contabilizar(turno: Turno) -> Turno:
        diario.sumar(costo_usd(turno.uso, agente.modelo))
        return turno

    app = FastAPI(
        title="Agente · Registro como Proveedor",
        version=f"prompt-v{instrucciones.version}",
        description="Prepara formularios y paquetes de registro como proveedor. "
        "Las acciones que deciden algo o salen hacia afuera requieren aprobación.",
    )
    app.add_exception_handler(RequestValidationError, _solicitud_no_valida)  # type: ignore[arg-type]

    # ---------- Rutas ----------

    @app.post("/api/chat", response_model=ChatResponse, responses=ERRORES)
    def chat(solicitud: ChatRequest, peticion: Request) -> ChatResponse:
        """Un mensaje de la analista. Sin `session_id`, empieza una conversación nueva."""
        if not modelo_configurado:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, SIN_MODELO)
        nueva = solicitud.session_id is None
        if not nueva:
            _obtener(sesiones, solicitud.session_id or "")  # 404 antes que un tope
        revisar_topes(peticion, conversacion_nueva=nueva)
        actual = _obtener_o_crear(sesiones, solicitud.session_id)
        if nueva:
            diario.contar_conversacion()
        turno = _en_exclusiva(
            actual, lambda: contabilizar(agente.responder(actual.sesion, solicitud.message))
        )
        return _registrar(actual, "message", solicitud.message, turno)

    @app.post(
        "/api/confirmations/{confirmation_id}", response_model=ChatResponse, responses=ERRORES
    )
    def confirmar(
        confirmation_id: Annotated[str, Path(pattern=PATRON_CONFIRMACION)],
        solicitud: ConfirmationRequest,
        peticion: Request,
    ) -> ChatResponse:
        """Aprobar (`approve: true`) o Rechazar (`false`) una acción pendiente de la sesión."""
        if not modelo_configurado:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, SIN_MODELO)
        actual = _obtener(sesiones, solicitud.session_id)
        if confirmation_id not in actual.sesion.pendientes:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"No hay ninguna acción pendiente «{confirmation_id}» en esta conversación "
                "(ya se resolvió, se canceló o no existe). No se ejecutó nada.",
            )
        # Aprobar o rechazar también consulta al modelo (para que continúe): cuenta igual.
        revisar_topes(peticion, conversacion_nueva=False)
        turno = _en_exclusiva(
            actual,
            lambda: contabilizar(
                agente.resolver(actual.sesion, confirmation_id, aprobar=solicitud.approve)
            ),
        )
        tipo = "approve" if solicitud.approve else "reject"
        return _registrar(actual, tipo, confirmation_id, turno)

    @app.get("/api/sessions/{session_id}", response_model=SessionResponse, responses=ERRORES)
    def historial(session_id: Annotated[str, Path(pattern=PATRON_SESION)]) -> SessionResponse:
        """La conversación tal como la vio la analista (nunca el historial crudo del modelo)."""
        actual = _obtener(sesiones, session_id)
        return SessionResponse(
            session_id=actual.id,
            created_at=actual.creada_en,
            turns=list(actual.turnos),
            pending=[de_confirmacion(p) for p in actual.sesion.pendientes.values()],
            usage=de_uso(actual.sesion.uso),
        )

    @app.get(
        "/api/cases/{case_id}/portal-values",
        response_model=PortalValuesResponse,
        responses=ERRORES,
    )
    def valores_portal(
        case_id: Annotated[str, Path(pattern=PATRON_ID_CASO)],
        session_id: Annotated[str, Query(pattern=PATRON_SESION)],
        respuesta: Response,
    ) -> PortalValuesResponse:
        """Paso 18 (D57) · Los valores del portal para copiar. Lo sensible va enmascarado.

        No pasa por el modelo. Se pide la sesión para leer el `out/` de esa conversación.
        Queda en log.jsonl que se vieron (sin los valores).
        """
        actual = _obtener(sesiones, session_id)
        ctx = actual.sesion.contexto
        try:
            caso = leer_caso(ctx.datos, case_id)
            mapeo = cargar_mapeo(ctx.salida / case_id)
        except ErrorDeDatos:
            raise HTTPException(status.HTTP_404_NOT_FOUND, CASO_NO_EXISTE) from None
        if caso.formato is not Formato.PORTAL:
            raise HTTPException(status.HTTP_404_NOT_FOUND, NO_ES_PORTAL)
        if mapeo is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, SIN_MAPEO)
        valores = valores_para_copiar(mapeo)
        enmascarados = sum(v.enmascarado for v in valores)
        escribir_auditoria(
            ctx.salida,
            RegistroLlamada(
                ts=ctx.reloj(),
                sesion=ctx.sesion_id,
                herramienta="vista_valores_portal",
                caso=case_id,
                ok=True,
                resumen=f"{len(valores)} valores mostrados ({enmascarados} "
                f"{'enmascarado' if enmascarados == 1 else 'enmascarados'})",
                duracion_ms=0,
            ),
        )
        # Que el navegador no guarde una copia de esta respuesta.
        respuesta.headers["Cache-Control"] = "no-store"
        return PortalValuesResponse(
            case=case_id,
            client=caso.cliente,
            fields=[
                PortalField(label=v.etiqueta, value=v.valor, status=v.estado, masked=v.enmascarado)
                for v in valores
            ],
            note=NOTA_PORTAL,
        )

    @app.get("/api/health", response_model=HealthResponse)
    def salud() -> HealthResponse:
        """¿Está vivo el servidor? Dice si hay modelo configurado, nunca la clave."""
        return HealthResponse(
            ok=True,
            provider=PROVEEDOR,
            model=modelo.modelo,
            llm_configured=modelo_configurado,
            prompt_version=instrucciones.version,
        )

    # ---------- Paso 16 · El front de chat ----------
    # Va AL FINAL: las rutas `/api/...` de arriba se revisan primero; todo lo demás se
    # busca como archivo en `web/` (`html=True`: "/" entrega `index.html`).
    app.middleware("http")(_encabezados_de_seguridad)
    app.mount("/", StaticFiles(directory=CARPETA_WEB, html=True), name="web")
    return app


# ---------- Piezas de las rutas ----------


def _obtener(sesiones: AlmacenDeSesiones, sesion_id: str) -> SesionApi:
    encontrada = sesiones.obtener(sesion_id)
    if encontrada is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SESION_NO_EXISTE)
    return encontrada


def _obtener_o_crear(sesiones: AlmacenDeSesiones, sesion_id: str | None) -> SesionApi:
    if sesion_id is not None:
        return _obtener(sesiones, sesion_id)
    try:
        return sesiones.nueva()
    except DemasiadasSesiones:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, DEMASIADAS) from None


def _en_exclusiva(actual: SesionApi, hacer: Callable[[], Turno]) -> Turno:
    """Ejecuta el turno con la sesión tomada: un segundo mensaje a la vez se rechaza (409)."""
    if not actual.candado.acquire(blocking=False):
        raise HTTPException(status.HTTP_409_CONFLICT, OCUPADA)
    try:
        return hacer()
    finally:
        actual.candado.release()


def _registrar(actual: SesionApi, tipo: str, entrada: str, turno: Turno) -> ChatResponse:
    """Convierte el turno en la respuesta de la API y lo guarda en el historial visible."""
    respuesta = de_turno(actual.id, turno)
    actual.turnos.append(
        TurnRecord.model_validate(
            {"at": actual.ultimo_uso, "kind": tipo, "input": entrada, "response": respuesta}
        )
    )
    return respuesta


async def _encabezados_de_seguridad(
    solicitud: Request, siguiente: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Agrega a cada respuesta los encabezados de seguridad del navegador (Paso 16).

    - CSP: la página solo puede cargar scripts, estilos e imágenes de ESTE servidor, y
      no se aceptan scripts escritos dentro del HTML. Si alguien lograra meter un
      `<script>` en una respuesta, el navegador no lo ejecutaría.
    - `nosniff`: el navegador no "adivina" el tipo de un archivo (un .txt no se ejecuta).
    - `no-referrer`: al salir a otro sitio no se le cuenta desde qué página se venía.

    `/docs` es la excepción: la página de FastAPI carga sus archivos de internet y usa
    scripts en línea. Es una herramienta para desarrolladores, no para la analista.
    """
    respuesta = await siguiente(solicitud)
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["Referrer-Policy"] = "no-referrer"
    if not solicitud.url.path.startswith(RUTAS_SIN_CSP):
        respuesta.headers["Content-Security-Policy"] = CSP
    return respuesta


async def _solicitud_no_valida(_: Request, error: RequestValidationError) -> JSONResponse:
    """Los errores de validación, en español y sin repetir lo que se envió.

    FastAPI, por defecto, responde en inglés y DEVUELVE el valor recibido; aquí solo se
    dice qué campo está mal y por qué.
    """
    problemas = "; ".join(describir_error_validacion(e) for e in error.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": f"solicitud no válida: {problemas}"},
    )
