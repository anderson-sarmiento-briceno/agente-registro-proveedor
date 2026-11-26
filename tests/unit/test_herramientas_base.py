"""Pruebas de `herramientas/base.py` con una herramienta de ejemplo.

La herramienta `proveedor_ejemplo` existe solo aquí, en un registro propio de las
pruebas (no se mezcla con las herramientas reales). Lee el maestro y devuelve datos
sensibles a propósito, para comprobar que nunca salen completos.

Con el argumento `modo` se le pide que falle de distintas formas:
    - "normal": funciona;
    - "datos_rotos": pide un caso que no existe (lanza `ErrorDeDatos`);
    - "prevista": lanza un `ErrorDeHerramienta` con un mensaje para la usuaria;
    - "explota": lanza un error inesperado cuyo mensaje trae un dato sensible.
En todos los casos, la herramienta debe responder un `Resultado` y nunca lanzar.

Criterio de "hecho" del Paso 3: una herramienta de ejemplo valida sus argumentos,
nunca lanza excepciones, escribe en log.jsonl y enmascara los valores sensibles.
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ValidationError
from structlog.testing import capture_logs

from registro_proveedor.config import Configuracion
from registro_proveedor.dominio.lectura import cargar_maestro, carpeta_de_caso
from registro_proveedor.herramientas.base import (
    ArgumentosHerramienta,
    Contexto,
    ErrorDeHerramienta,
    IdCasoArg,
    Registro,
    Resultado,
)

CUENTA_COMPLETA = "03100012345"  # número de cuenta del maestro de ejemplo
CEDULA_COMPLETA = "71555123"  # identificación del representante legal

# ---------- La herramienta de ejemplo ----------

registro = Registro()


class ArgsEjemplo(ArgumentosHerramienta):
    caso: IdCasoArg
    modo: Literal["normal", "datos_rotos", "prevista", "explota"] = "normal"


class DatosEjemplo(BaseModel):
    razon_social: str
    nit: str
    numero_cuenta: str  # sensible
    identificacion: str  # sensible


@registro.herramienta(
    nombre="proveedor_ejemplo",
    descripcion="Herramienta de ejemplo: lee datos del maestro.",
    argumentos=ArgsEjemplo,
    resumir=lambda d: f"leída «{d.razon_social}»",
)
def ejemplo(args: ArgsEjemplo, ctx: Contexto) -> Resultado[DatosEjemplo]:
    if args.modo == "datos_rotos":
        carpeta_de_caso(ctx.datos, "no-existe")
    if args.modo == "prevista":
        raise ErrorDeHerramienta("el caso no tiene plantilla")
    if args.modo == "explota":
        raise RuntimeError(f"fallo inesperado con la cuenta {CUENTA_COMPLETA}")
    maestro = cargar_maestro(ctx.datos)
    assert maestro.banco is not None and maestro.banco.numero_cuenta is not None
    assert maestro.representante_legal is not None
    assert maestro.representante_legal.identificacion is not None
    ctx.carpeta_de_salida(args.caso)  # crea out/<caso>/
    return Resultado(
        ok=True,
        data=DatosEjemplo(
            razon_social=maestro.razon_social,
            nit=maestro.nit,
            numero_cuenta=maestro.banco.numero_cuenta,
            identificacion=maestro.representante_legal.identificacion,
        ),
    )


@registro.herramienta(
    nombre="proveedor_con_aprobacion",
    descripcion="Herramienta de ejemplo que requiere aprobación humana.",
    argumentos=ArgsEjemplo,
    requiere_confirmacion=True,
)
def con_aprobacion(args: ArgsEjemplo, ctx: Contexto) -> Resultado[None]:
    return Resultado(ok=True)


def _log(contexto: Contexto, caso: str | None = None) -> list[dict[str, object]]:
    """Las líneas del log de auditoría (global o de un caso)."""
    archivo = contexto.salida / (caso or "") / "log.jsonl"
    return [json.loads(linea) for linea in archivo.read_text(encoding="utf-8").splitlines()]


# ---------- Funciona y deja registro ----------


def test_llamada_directa_desde_python(contexto: Contexto) -> None:
    """Como la usará demo.py: los datos completos y con su tipo exacto."""
    resultado = ejemplo(ArgsEjemplo(caso="ec-corp-andina"), contexto)
    assert resultado.ok and resultado.error is None
    assert resultado.data is not None
    assert resultado.data.razon_social == "Empresa Ejemplo S.A.S."


def test_llamada_desde_el_agente(contexto: Contexto) -> None:
    """Como la usará el agente: por nombre y con un diccionario de argumentos."""
    resultado = registro.ejecutar("proveedor_ejemplo", {"caso": "ec-corp-andina"}, contexto)
    assert resultado.ok


def test_deja_registro_global_y_por_caso(contexto: Contexto) -> None:
    ejemplo(ArgsEjemplo(caso="ec-corp-andina"), contexto)
    linea = _log(contexto, "ec-corp-andina")[0]
    assert linea["ts"] == "2026-09-01T12:00:00Z"  # el reloj fijo del contexto
    assert linea["sesion"] == "sesion-de-prueba"
    assert linea["herramienta"] == "proveedor_ejemplo"
    assert linea["ok"] is True
    assert linea["resumen"] == "leída «Empresa Ejemplo S.A.S.»"  # la frase de `resumir`
    assert isinstance(linea["duracion_ms"], int)
    assert _log(contexto) == [linea]  # la misma línea en el log global


# ---------- Enmascaramiento: los datos sensibles no salen completos ----------


def test_a_json_enmascara_lo_sensible(contexto: Contexto) -> None:
    texto = ejemplo(ArgsEjemplo(caso="ec-corp-andina"), contexto).a_json()
    datos = json.loads(texto)["data"]
    assert datos["numero_cuenta"] == "****2345"
    assert datos["identificacion"] == "****5123"
    assert datos["nit"] == "900123456"  # el NIT no se enmascara (decisión del Paso 3)
    assert CUENTA_COMPLETA not in texto and CEDULA_COMPLETA not in texto


def test_ningun_log_contiene_datos_sensibles(contexto: Contexto) -> None:
    for modo in ("normal", "explota"):
        registro.ejecutar("proveedor_ejemplo", {"caso": "ec-corp-andina", "modo": modo}, contexto)
    for archivo in contexto.salida.rglob("log.jsonl"):
        texto = archivo.read_text(encoding="utf-8")
        assert CUENTA_COMPLETA not in texto
        assert CEDULA_COMPLETA not in texto


# ---------- Argumentos inválidos: se rechazan sin ejecutar ----------


@pytest.mark.parametrize(
    ("argumentos", "esperado"),
    [
        ({"caso": "../repositorio"}, "«caso»: el valor «../repositorio» no es válido"),
        ({}, "«caso»: falta este campo obligatorio"),
        ({"caso": "ec-corp-andina", "enviar": True}, "«enviar»: campo no reconocido"),
        ({"caso": "ec-corp-andina", "modo": "turbo"}, "«modo»: el valor «turbo» no es válido"),
    ],
)
def test_argumentos_invalidos(
    contexto: Contexto, argumentos: dict[str, object], esperado: str
) -> None:
    resultado = registro.ejecutar("proveedor_ejemplo", argumentos, contexto)
    assert not resultado.ok
    assert resultado.error is not None
    assert resultado.error.startswith("argumentos no válidos:")
    assert esperado in resultado.error
    # Se registró en el log global, pero no se creó ninguna carpeta de caso.
    assert _log(contexto)[0]["ok"] is False
    assert [p.name for p in contexto.salida.iterdir()] == ["log.jsonl"]


def test_herramienta_inexistente(contexto: Contexto) -> None:
    resultado = registro.ejecutar("proveedor_enviar_todo", {}, contexto)
    assert not resultado.ok
    assert resultado.error is not None
    assert "no existe la herramienta «proveedor_enviar_todo»" in resultado.error
    assert "proveedor_ejemplo" in resultado.error  # dice cuáles sí existen


# ---------- Errores: nunca se lanza una excepción ----------


def test_dato_roto_se_explica_sin_rutas_del_computador(contexto: Contexto) -> None:
    resultado = registro.ejecutar(
        "proveedor_ejemplo", {"caso": "ec-corp-andina", "modo": "datos_rotos"}, contexto
    )
    assert not resultado.ok
    assert resultado.error == "datos/casos: no existe el caso «no-existe»"
    # El mensaje no revela la ruta completa del computador (C:/Users/...).
    assert str(contexto.datos.resolve().parent) not in resultado.error


def test_error_previsto_se_muestra_tal_cual(contexto: Contexto) -> None:
    resultado = ejemplo(ArgsEjemplo(caso="ec-corp-andina", modo="prevista"), contexto)
    assert resultado == Resultado(ok=False, error="el caso no tiene plantilla")


def test_error_inesperado_no_filtra_su_mensaje(contexto: Contexto) -> None:
    # `capture_logs` atrapa lo que se escribe en el log de operación durante el bloque.
    with capture_logs() as logs:
        resultado = ejemplo(ArgsEjemplo(caso="ec-corp-andina", modo="explota"), contexto)
    assert not resultado.ok
    assert resultado.error is not None
    assert "error interno en la herramienta «proveedor_ejemplo»" in resultado.error
    assert CUENTA_COMPLETA not in resultado.error  # el mensaje original no llega al modelo
    # El detalle sí queda en el log de operación, para poder depurar.
    assert logs[0]["event"] == "error_inesperado_en_herramienta"
    assert logs[0]["herramienta"] == "proveedor_ejemplo"


def test_si_resumir_falla_la_llamada_sigue_siendo_exitosa(contexto: Contexto) -> None:
    registro_local = Registro()

    def resumen_que_falla(_: str) -> str:
        raise ValueError("fallo al resumir")

    @registro_local.herramienta(
        nombre="proveedor_resumen_roto",
        descripcion="Ejemplo.",
        argumentos=ArgsEjemplo,
        resumir=resumen_que_falla,
    )
    def herramienta(args: ArgsEjemplo, ctx: Contexto) -> Resultado[str]:
        return Resultado(ok=True, data="hola")

    with capture_logs():
        assert herramienta(ArgsEjemplo(caso="ec-corp-andina"), contexto).ok
    assert _log(contexto)[0]["resumen"] == "ok"


# ---------- Registro ----------


def test_esquema_para_el_modelo(contexto: Contexto) -> None:
    """El JSON Schema que verá el LLM sale del mismo modelo que valida."""
    h = registro.obtener("proveedor_ejemplo")
    assert h is not None
    assert h.descripcion == "Herramienta de ejemplo: lee datos del maestro."
    esquema = h.esquema_parametros()
    assert esquema["required"] == ["caso"]
    assert esquema["additionalProperties"] is False  # no acepta argumentos inventados
    caso = esquema["properties"]["caso"]
    assert "datos/casos/" in caso["description"]
    assert "pattern" in caso


def test_marca_de_confirmacion() -> None:
    con = registro.obtener("proveedor_con_aprobacion")
    sin = registro.obtener("proveedor_ejemplo")
    assert con is not None and con.requiere_confirmacion
    assert sin is not None and not sin.requiere_confirmacion


def test_listar_en_orden_alfabetico() -> None:
    assert [h.nombre for h in registro.listar()] == [
        "proveedor_con_aprobacion",
        "proveedor_ejemplo",
    ]


@pytest.mark.parametrize("nombre", ["Proveedor-Malo", "", "con espacio"])
def test_nombre_de_herramienta_invalido(nombre: str) -> None:
    with pytest.raises(ValueError, match="nombre de herramienta no válido"):
        Registro().herramienta(nombre=nombre, descripcion="x", argumentos=ArgsEjemplo)(ejemplo)


def test_nombre_repetido() -> None:
    with pytest.raises(ValueError, match="ya está registrada"):
        registro.herramienta(nombre="proveedor_ejemplo", descripcion="x", argumentos=ArgsEjemplo)(
            ejemplo
        )


# ---------- Resultado ----------


def test_resultado_incoherente_se_rechaza() -> None:
    with pytest.raises(ValidationError, match="ok=True no puede tener error"):
        Resultado(ok=True, error="x")
    with pytest.raises(ValidationError, match="ok=False necesita un mensaje"):
        Resultado(ok=False)


# ---------- Contexto ----------


def test_carpeta_de_salida(contexto: Contexto) -> None:
    carpeta = contexto.carpeta_de_salida("ec-corp-andina")
    assert carpeta.is_dir()
    assert carpeta == (contexto.salida / "ec-corp-andina").resolve()


@pytest.mark.parametrize("caso", ["../fuera", "..", "Caso Malo"])
def test_carpeta_de_salida_no_sale_de_out(contexto: Contexto, caso: str) -> None:
    with pytest.raises(ErrorDeHerramienta, match="no es válido"):
        contexto.carpeta_de_salida(caso)


def test_contexto_desde_configuracion() -> None:
    config = Configuracion(_env_file=None, fecha_ejecucion="2026-09-01")  # type: ignore[call-arg]
    ctx = Contexto.desde_configuracion(config, sesion_id="abc")
    assert ctx.fecha_ejecucion == date(2026, 9, 1)
    assert ctx.sesion_id == "abc"
    assert ctx.datos.name == "datos" and ctx.salida.name == "out"
    assert isinstance(ctx.salida, Path)


def test_con_fecha_fija_el_reloj_marca_ese_dia() -> None:
    """Demo coherente: con FECHA_EJECUCION fija, las aprobaciones y el log llevan ese día."""
    config = Configuracion(fecha_ejecucion=date(2026, 9, 20))
    ahora = Contexto.desde_configuracion(config).reloj()
    assert ahora.date() == date(2026, 9, 20)
    assert ahora.tzinfo is not None  # con zona horaria (UTC), como el resto del log


def test_sin_fecha_fija_el_reloj_es_el_real() -> None:
    ahora = Contexto.desde_configuracion(Configuracion()).reloj()
    assert abs((datetime.now(UTC) - ahora).total_seconds()) < 5
