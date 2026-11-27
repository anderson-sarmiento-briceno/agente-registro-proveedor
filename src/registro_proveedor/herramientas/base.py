"""Contrato común de las herramientas: `Resultado`, `Contexto`, `@herramienta` y `Registro`.

¿Por qué existe este archivo?
    El proyecto tendrá 7 herramientas (leer solicitud, mapear campos, generar
    formulario...). Todas deben comportarse igual:
    1. revisar sus argumentos antes de hacer nada;
    2. no lanzar NUNCA una excepción: siempre responder `ok=True` con los datos
       u `ok=False` con un mensaje claro (principio 6, HU-6);
    3. dejar registro de cada llamada en `log.jsonl` (RN5, CA4);
    4. no dejar salir datos sensibles completos (RN8).
    En vez de repetir eso en cada herramienta, se escribe una sola vez aquí. Cada
    herramienta solo se ocupa de su trabajo.

¿Cómo se usa? (ejemplo de lo que vendrá en el Paso 4)

    registro = Registro()

    class LeerSolicitudArgs(ArgumentosHerramienta):
        caso: IdCasoArg

    @registro.herramienta(
        nombre="proveedor_leer_solicitud",
        descripcion="Lee la solicitud de un caso y devuelve país, formato, campos y soportes.",
        argumentos=LeerSolicitudArgs,
    )
    def leer_solicitud(args: LeerSolicitudArgs, ctx: Contexto) -> Resultado[SolicitudLeida]:
        ...

Dos formas de llamar a una herramienta:
    - Desde Python (demo.py, pruebas): `leer_solicitud(LeerSolicitudArgs(caso="x"), ctx)`.
      Los argumentos ya vienen validados porque se construyeron con su modelo.
    - Desde el agente: `registro.ejecutar("proveedor_leer_solicitud", {"caso": "x"}, ctx)`.
      El modelo de lenguaje manda un diccionario cualquiera; aquí se valida primero.
    En los dos casos se aplican la captura de errores y el registro en log.jsonl.
"""

import functools
import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from registro_proveedor.config import RAIZ_PROYECTO, Configuracion
from registro_proveedor.dominio.lectura import ErrorDeDatos, describir_error_validacion
from registro_proveedor.dominio.modelos import PATRON_ID_CASO
from registro_proveedor.observabilidad import (
    RegistroLlamada,
    enmascarar_datos,
    escribir_auditoria,
    obtener_logger,
)

# Nombre de herramienta que ve el modelo: minúsculas y guiones bajos, como
# "proveedor_leer_solicitud". (Los proveedores de LLM exigen un formato parecido.)
PATRON_NOMBRE_HERRAMIENTA = r"^[a-z][a-z0-9_]{0,63}$"


# ---------- Resultado: la respuesta de toda herramienta ----------


class Resultado[T](BaseModel):
    """La respuesta de toda herramienta: `{ok, data, error}`.

    `[T]` lo hace genérico: `Resultado[SolicitudLeida]` dice que, si sale bien,
    `data` es una `SolicitudLeida`. Así mypy sabe qué hay dentro.

    Reglas (las revisa `_coherente`):
    - ok=True  → hay `data` (puede ser None si no hay nada que devolver) y NO hay error.
    - ok=False → hay un `error` (mensaje claro para personas, sin traza técnica).
    """

    model_config = ConfigDict(frozen=True)

    ok: bool
    data: T | None = None
    error: str | None = None

    @model_validator(mode="after")
    def _coherente(self) -> "Resultado[T]":
        if self.ok and self.error is not None:
            raise ValueError("un Resultado con ok=True no puede tener error")
        if not self.ok and not self.error:
            raise ValueError("un Resultado con ok=False necesita un mensaje de error")
        return self

    def a_json(self) -> str:
        """El resultado como texto JSON, con los datos sensibles enmascarados.

        Es la ÚNICA forma en que un resultado debe salir hacia el modelo de lenguaje
        o la API. Los valores completos solo se escriben en los archivos generados
        en `out/` (principio 4: al modelo, solo los datos mínimos).
        """
        return json.dumps(enmascarar_datos(self.model_dump(mode="json")), ensure_ascii=False)


class ErrorDeHerramienta(Exception):
    """Error previsto dentro de una herramienta, con un mensaje listo para la usuaria.

    Una herramienta puede lanzarlo ("el caso no tiene plantilla") y el decorador lo
    convierte en `Resultado(ok=False, error=mensaje)`. Así el código de la
    herramienta queda simple y la regla "nunca lanzar hacia el agente" se cumple igual.
    """


# ---------- Argumentos ----------


class ArgumentosHerramienta(BaseModel):
    """Base de los argumentos de toda herramienta.

    extra="forbid": si el modelo de lenguaje inventa un argumento que no existe
    (`{"caso": "x", "enviar": true}`), se rechaza en vez de ignorarlo en silencio.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


# Argumento "caso" reutilizable. La descripción la lee el modelo de lenguaje para
# saber qué poner; el patrón impide nombres como "../secreto".
IdCasoArg = Annotated[
    str,
    Field(
        pattern=PATRON_ID_CASO,
        description="Nombre de la carpeta del caso dentro de datos/casos/, "
        "por ejemplo «ec-corp-andina».",
    ),
]


# ---------- Contexto: lo que toda herramienta recibe ----------


def _ahora_utc() -> datetime:
    return datetime.now(UTC)


def reloj_para(fecha_fija: date | None) -> Callable[[], datetime]:
    """El reloj del contexto: la hora real o, con una fecha fija, ese día a la hora actual.

    Así todas las marcas de tiempo (aprobaciones, paquete, constancia, log.jsonl) son
    coherentes con la fecha de ejecución de una demostración.
    """
    if fecha_fija is None:
        return _ahora_utc

    def ahora_en_la_fecha_fija() -> datetime:
        return datetime.combine(fecha_fija, datetime.now(UTC).time(), tzinfo=UTC)

    return ahora_en_la_fecha_fija


@dataclass(frozen=True)
class Aprobacion:
    """La aprobación de la analista para UNA acción concreta (CA3, Paso 13).

    La crea el ciclo del agente solo cuando la analista pulsa Aprobar, y la pone en el
    `Contexto` con el que se ejecuta esa acción. Sirve para UNA herramienta con UNOS
    argumentos exactos: no se puede usar para otra herramienta ni para otros argumentos.
    """

    id: str  # el de la confirmación pendiente que se aprobó
    herramienta: str
    argumentos: Mapping[str, object]  # ya validados (`model_dump(mode="json")`)
    por: str  # quién aprobó
    en: datetime  # cuándo


@dataclass(frozen=True)
class Contexto:
    """Lo que toda herramienta necesita, además de sus argumentos.

    Se pasa como parámetro (en vez de leerlo de variables globales) para que en las
    pruebas se pueda usar otra carpeta de salida, otra fecha y otro reloj.
    """

    datos: Path  # carpeta de insumos (solo lectura)
    salida: Path  # carpeta de resultados: out/
    fecha_ejecucion: date  # RN7: contra esta fecha se revisan las vigencias
    sesion_id: str = "local"
    # Archivo de reglas de negocio (Paso 6). Las pruebas pueden usar uno propio para
    # comprobar que cambiar un número en el YAML cambia el resultado.
    reglas: Path = RAIZ_PROYECTO / "config" / "reglas.yaml"
    # Quién está trabajando: queda registrado en las confirmaciones (HU-2). En el MVP
    # hay una sola usuaria; con inicio de sesión (Paso 18) será su nombre de usuario.
    usuario: str = "analista"
    # Función que da la hora actual, para el `ts` del log. En pruebas se reemplaza
    # por una que siempre da la misma hora, y así el log es predecible.
    reloj: Callable[[], datetime] = field(default=_ahora_utc)
    # Paso 13 · Doble candado: las herramientas marcadas `requiere_confirmacion` solo se
    # ejecutan si aquí viene una aprobación para ESA herramienta y ESOS argumentos. Lo
    # normal es None: solo el ciclo del agente la pone, después de que la analista aprueba.
    aprobacion: Aprobacion | None = None

    @classmethod
    def desde_configuracion(cls, config: Configuracion, sesion_id: str = "local") -> "Contexto":
        """El contexto normal del proyecto: datos/ y out/ en la raíz, fecha de la configuración.

        Si `FECHA_EJECUCION` está fija (una demostración), el reloj también usa ESE día
        (con la hora actual). Si no, una aprobación quedaría registrada en noviembre en
        un caso que se trabaja "el 20 de septiembre", y eso confunde a quien lo revisa.
        """
        return cls(
            datos=config.datos_efectivos(),  # Paso 21: `datos/`, o la del piloto
            salida=RAIZ_PROYECTO / "out",
            fecha_ejecucion=config.fecha_efectiva(),
            sesion_id=sesion_id,
            reloj=reloj_para(config.fecha_ejecucion),
        )

    def carpeta_de_salida(self, caso: str) -> Path:
        """Devuelve (y crea si falta) `out/<caso>/`, comprobando que no se salga de `out/`.

        Misma doble defensa que `carpeta_de_caso` en lectura.py: el nombre debe cumplir
        el patrón, y la ruta resuelta debe quedar dentro de `out/`.
        """
        salida = self.salida.resolve()
        carpeta = (salida / caso).resolve()
        if not re.fullmatch(PATRON_ID_CASO, caso) or not carpeta.is_relative_to(salida):
            raise ErrorDeHerramienta(f"el nombre de caso «{caso}» no es válido")
        carpeta.mkdir(parents=True, exist_ok=True)
        return carpeta

    def ruta_en_salida(self, *partes: str) -> str:
        """Cómo se nombra un archivo generado ante el modelo y la analista: "out/<caso>/…".

        Siempre empieza por "out/", aunque la carpeta real sea otra: en la demo publicada
        cada conversación escribe en `out/sesiones/<id>/` (Paso 19), y mostrar ese id
        largo en el chat solo confunde. Lo que importa es el caso y el archivo.
        """
        return "/".join(("out", *partes))

    def ruta_legible(self, ruta: Path) -> str:
        """Ruta corta para mensajes: "datos/casos/x/solicitud.json" en vez de "C:/Users/...".

        Así un mensaje de error no le muestra al modelo la estructura del computador.
        """
        try:
            return ruta.resolve().relative_to(self.datos.resolve().parent).as_posix()
        except ValueError:
            return ruta.name


# ---------- Registro y decorador ----------

# Una herramienta ya "envuelta": recibe argumentos validados y el contexto, y
# devuelve un Resultado. Se usa `Any` porque el registro guarda herramientas con
# argumentos y datos de tipos distintos: en esta lista el tipo exacto se pierde a
# propósito, y se recupera validando con `modelo_args` antes de llamar.
FuncionSegura = Callable[[Any, Contexto], Resultado[Any]]


@dataclass(frozen=True)
class Herramienta:
    """Una herramienta registrada: lo que el agente necesita saber de ella."""

    nombre: str
    descripcion: str  # una frase: es lo único que el modelo lee para decidir usarla
    modelo_args: type[ArgumentosHerramienta]
    # Si es True, el servidor no la ejecuta al pedirla, sino que pide aprobación
    # humana (CA3): el ciclo crea una confirmación pendiente, y la herramienta solo
    # corre con una `Aprobacion` válida en el contexto (doble candado, Paso 13).
    requiere_confirmacion: bool
    funcion: FuncionSegura
    # La función que resume los datos del resultado en una frase (la del log). El ciclo
    # del agente (Paso 12) la usa para mostrar qué devolvió cada herramienta.
    resumir: Callable[[Any], str] | None = None

    def esquema_parametros(self) -> dict[str, Any]:
        """JSON Schema de los argumentos, generado por Pydantic.

        Es lo que el modelo de lenguaje recibe para saber qué argumentos mandar.
        Como sale del mismo modelo que valida, nunca se desincroniza con el código.
        (`Any` porque un JSON Schema es un diccionario con valores de muchos tipos.)
        """
        return self.modelo_args.model_json_schema()


class Registro:
    """La lista de herramientas disponibles.

    El proyecto tendrá un registro con las herramientas reales. Las pruebas crean
    el suyo, para que una herramienta de ejemplo nunca se mezcle con las reales.
    """

    def __init__(self) -> None:
        self._herramientas: dict[str, Herramienta] = {}

    def herramienta[A: ArgumentosHerramienta, D](
        self,
        *,
        nombre: str,
        descripcion: str,
        argumentos: type[A],
        requiere_confirmacion: bool = False,
        resumir: Callable[[D], str] | None = None,
    ) -> Callable[[Callable[[A, Contexto], Resultado[D]]], Callable[[A, Contexto], Resultado[D]]]:
        """Decorador que registra una función como herramienta y la vuelve "segura".

        Un decorador es una función que recibe otra función y devuelve una versión
        mejorada. Se escribe con `@` encima de la definición.

        Parámetros:
            nombre: el que ve el modelo, como "proveedor_leer_solicitud".
            descripcion: una frase clara; el modelo decide con ella cuándo usarla.
            argumentos: la clase de los argumentos (un `ArgumentosHerramienta`).
            requiere_confirmacion: si necesita aprobación humana (Paso 13).
            resumir: función opcional que convierte los datos del resultado en una
                frase para el log ("3 campos llenos, 1 faltante"). Sin ella, "ok".

        `[A, D]`: A es el tipo de los argumentos y D el de los datos que devuelve.
        Sirven para que la función decorada conserve sus tipos exactos.

        Los errores de programación (nombre inválido o repetido) sí lanzan una
        excepción, al importar el módulo: eso se debe ver de inmediato, no en una
        conversación con la usuaria.
        """

        def decorar(
            funcion: Callable[[A, Contexto], Resultado[D]],
        ) -> Callable[[A, Contexto], Resultado[D]]:
            if not re.fullmatch(PATRON_NOMBRE_HERRAMIENTA, nombre):
                raise ValueError(f"nombre de herramienta no válido: «{nombre}»")
            if nombre in self._herramientas:
                raise ValueError(f"la herramienta «{nombre}» ya está registrada")
            segura = _envolver(nombre, funcion, resumir, requiere_confirmacion)
            self._herramientas[nombre] = Herramienta(
                nombre=nombre,
                descripcion=descripcion,
                modelo_args=argumentos,
                requiere_confirmacion=requiere_confirmacion,
                funcion=segura,
                resumir=resumir,
            )
            return segura

        return decorar

    def obtener(self, nombre: str) -> Herramienta | None:
        return self._herramientas.get(nombre)

    def resumir(self, nombre: str, resultado: Resultado[Any]) -> str:
        """La frase que resume un resultado, la misma del log: el error si falló.

        Así el chat muestra exactamente lo mismo que quedó en `log.jsonl`.
        """
        encontrada = self.obtener(nombre)
        return _resumen(nombre, resultado, encontrada.resumir if encontrada else None)

    def listar(self) -> list[Herramienta]:
        """Las herramientas, en orden alfabético (así la lista que ve el modelo es estable)."""
        return [self._herramientas[n] for n in sorted(self._herramientas)]

    def ejecutar(
        self, nombre: str, argumentos: Mapping[str, object], ctx: Contexto
    ) -> Resultado[Any]:
        """Ejecuta una herramienta por su nombre, con argumentos que aún no se han validado.

        Es lo que usará el agente: el modelo de lenguaje manda el nombre y un
        diccionario de argumentos, que podrían estar mal o ser inventados. Si la
        herramienta no existe o los argumentos no son válidos, responde `ok=False`
        sin ejecutar nada (y lo deja en el log).
        """
        inicio = time.perf_counter()
        encontrada, args, error = self._validar(nombre, argumentos)
        if encontrada is None or args is None:
            resultado: Resultado[Any] = Resultado(ok=False, error=error)
            _registrar(ctx, nombre, None, resultado, None, inicio)
            return resultado
        return encontrada.funcion(args, ctx)

    def validar_argumentos(
        self, nombre: str, argumentos: Mapping[str, object]
    ) -> Resultado[dict[str, Any]]:
        """Revisa la herramienta y sus argumentos SIN ejecutarla.

        Devuelve los argumentos normalizados (como quedan después de validarlos, con los
        valores por defecto incluidos), o un error claro. El ciclo del agente lo usa
        antes de crear una confirmación pendiente (Paso 13): no tiene sentido pedirle a
        la analista que apruebe algo que de todas formas fallaría.
        """
        _, args, error = self._validar(nombre, argumentos)
        if args is None:
            return Resultado(ok=False, error=error)
        return Resultado(ok=True, data=args.model_dump(mode="json"))

    def _validar(
        self, nombre: str, argumentos: Mapping[str, object]
    ) -> tuple[Herramienta | None, ArgumentosHerramienta | None, str]:
        """(herramienta, argumentos validados, "") o (…, None, mensaje de error)."""
        encontrada = self.obtener(nombre)
        if encontrada is None:
            disponibles = ", ".join(sorted(self._herramientas)) or "ninguna"
            return None, None, f"no existe la herramienta «{nombre}». Disponibles: {disponibles}"
        try:
            return encontrada, encontrada.modelo_args.model_validate(argumentos), ""
        except ValidationError as e:
            problemas = "; ".join(describir_error_validacion(err) for err in e.errors())
            return encontrada, None, f"argumentos no válidos: {problemas}"


# ---------- Detalles internos ----------


SIN_APROBACION = (
    "esta acción requiere la aprobación de la analista y no se ejecutó: "
    "no hay una aprobación válida para esta herramienta con estos argumentos"
)


def _envolver[A: ArgumentosHerramienta, D](
    nombre: str,
    funcion: Callable[[A, Contexto], Resultado[D]],
    resumir: Callable[[D], str] | None,
    requiere_confirmacion: bool,
) -> Callable[[A, Contexto], Resultado[D]]:
    """Crea la versión "segura" de una herramienta: nunca lanza y siempre deja registro.

    Si la herramienta requiere confirmación, además exige una aprobación válida en el
    contexto (el doble candado del Paso 13). Este control está AQUÍ, y no solo en el
    ciclo del agente, para que nadie pueda saltárselo: ni el modelo, ni un error del
    ciclo, ni una llamada directa desde otro código.
    """

    # `functools.wraps` copia el nombre y la documentación de la función original,
    # para que la versión envuelta se vea igual al inspeccionarla.
    @functools.wraps(funcion)
    def segura(args: A, ctx: Contexto) -> Resultado[D]:
        inicio = time.perf_counter()
        if requiere_confirmacion and not _esta_aprobada(ctx, nombre, args):
            bloqueada: Resultado[D] = Resultado(ok=False, error=SIN_APROBACION)
            _registrar(ctx, nombre, _caso_de(args), bloqueada, resumir, inicio)
            return bloqueada
        try:
            resultado = funcion(args, ctx)
        except ErrorDeDatos as e:
            # Un dato roto (Paso 2): se explica con sus problemas en español.
            detalle = "; ".join(e.problemas)
            resultado = Resultado(ok=False, error=f"{ctx.ruta_legible(e.archivo)}: {detalle}")
        except ErrorDeHerramienta as e:
            resultado = Resultado(ok=False, error=str(e))
        except Exception:
            # Cualquier otro error es un fallo nuestro, no de la usuaria. El detalle
            # técnico va SOLO al log de operación: el mensaje de la excepción podría
            # contener datos sensibles o rutas del computador.
            obtener_logger().exception("error_inesperado_en_herramienta", herramienta=nombre)
            resultado = Resultado(
                ok=False,
                error=f"error interno en la herramienta «{nombre}». "
                "El detalle quedó en el log de operación.",
            )
        _registrar(ctx, nombre, _caso_de(args), resultado, resumir, inicio)
        return resultado

    return segura


def _esta_aprobada(ctx: Contexto, nombre: str, args: ArgumentosHerramienta) -> bool:
    """¿Hay en el contexto una aprobación para ESTA herramienta con ESTOS argumentos?"""
    aprobacion = ctx.aprobacion
    return (
        aprobacion is not None
        and aprobacion.herramienta == nombre
        and dict(aprobacion.argumentos) == args.model_dump(mode="json")
    )


def _caso_de(args: object) -> str | None:
    """El caso de la llamada, si los argumentos tienen uno válido (para el log por caso)."""
    caso = getattr(args, "caso", None)
    return caso if isinstance(caso, str) and re.fullmatch(PATRON_ID_CASO, caso) else None


def _registrar[D](
    ctx: Contexto,
    herramienta: str,
    caso: str | None,
    resultado: Resultado[D],
    resumir: Callable[[D], str] | None,
    inicio: float,
) -> None:
    """Escribe la línea de auditoría de una llamada en log.jsonl."""
    escribir_auditoria(
        ctx.salida,
        RegistroLlamada(
            ts=ctx.reloj(),
            sesion=ctx.sesion_id,
            herramienta=herramienta,
            caso=caso,
            ok=resultado.ok,
            resumen=_resumen(herramienta, resultado, resumir),
            duracion_ms=round((time.perf_counter() - inicio) * 1000),
            aprobacion=ctx.aprobacion.id if ctx.aprobacion else None,
        ),
    )


def _resumen[D](
    herramienta: str, resultado: Resultado[D], resumir: Callable[[D], str] | None
) -> str:
    """La frase del log: el error si falló; si salió bien, la de `resumir` o "ok"."""
    if not resultado.ok:
        return resultado.error or "error"
    if resumir is None or resultado.data is None:
        return "ok"
    try:
        return resumir(resultado.data)
    except Exception:
        # Un fallo al resumir no debe convertir en error una llamada que salió bien.
        obtener_logger().exception("error_al_resumir", herramienta=herramienta)
        return "ok"
