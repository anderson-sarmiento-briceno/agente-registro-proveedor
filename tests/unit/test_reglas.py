"""Pruebas de `dominio/reglas.py` y `config/reglas.yaml`: una o más por cada regla.

Cómo está organizado:
    1. El archivo de reglas real se lee, y uno mal escrito da errores claros.
    2. RN3 y RN6: vigencia de los soportes (presente, por vencer, vencido, ausente) y
       qué bloquea la firma.
    3. RN2: qué es un dato bancario.
    4. Lo que pide el plan: cambiar un número en el YAML cambia el resultado, sin tocar
       el código.

La regla RN1 (identificador extranjero) se prueba en test_mapeo.py, porque se aplica
dentro del mapeo.
"""

import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from registro_proveedor.config import RAIZ_PROYECTO
from registro_proveedor.dominio.lectura import ErrorDeDatos, cargar_indice_soportes
from registro_proveedor.dominio.modelos import Pais, TipoSoporte
from registro_proveedor.dominio.reglas import (
    EstadoSoporte,
    ReglaVigencias,
    bloquean_firma,
    cargar_reglas,
    es_dato_bancario,
    evaluar_soporte,
    evaluar_soportes,
)
from registro_proveedor.herramientas.base import Contexto
from registro_proveedor.herramientas.proveedor import registro
from tests.ayudas import DATOS_REALES, FECHA_FIJA, EditarJson, como_dict, como_lista

ARCHIVO_REAL = RAIZ_PROYECTO / "config" / "reglas.yaml"
REGLAS = cargar_reglas(ARCHIVO_REAL)
INDICE = cargar_indice_soportes(DATOS_REALES)
QUINCE_DIAS = ReglaVigencias(dias_por_vencer=15)


def _yaml_con(tmp_path: Path, **cambios: dict[str, object]) -> Path:
    """Copia de reglas.yaml con algunas secciones modificadas. Devuelve su ruta."""
    contenido = yaml.safe_load(ARCHIVO_REAL.read_text(encoding="utf-8"))
    for seccion, valores in cambios.items():
        contenido[seccion] = {**contenido[seccion], **valores}
    ruta = tmp_path / "reglas.yaml"
    ruta.write_text(yaml.safe_dump(contenido, allow_unicode=True), encoding="utf-8")
    return ruta


# ---------- 1. El archivo de reglas ----------


def test_reglas_reales() -> None:
    assert REGLAS.mapeo.umbral_lleno == 0.9
    assert REGLAS.mapeo.umbral_confirmar == 0.8
    assert REGLAS.identificador_tributario.pais_empresa is Pais.COLOMBIA
    assert REGLAS.identificador_tributario.por_pais[Pais.HONDURAS] == "RTN"
    assert REGLAS.vigencias.dias_por_vencer == 15


def test_archivo_inexistente(tmp_path: Path) -> None:
    with pytest.raises(ErrorDeDatos, match="no existe el archivo de reglas"):
        cargar_reglas(tmp_path / "nada.yaml")


def test_yaml_mal_escrito(tmp_path: Path) -> None:
    ruta = tmp_path / "reglas.yaml"
    ruta.write_text("mapeo:\n  umbral_lleno: [0.9\n", encoding="utf-8")  # falta el "]"
    with pytest.raises(ErrorDeDatos, match=r"no es un YAML válido \(línea"):
        cargar_reglas(ruta)


def test_umbrales_en_desorden(tmp_path: Path) -> None:
    ruta = _yaml_con(tmp_path, mapeo={"umbral_confirmar": 0.95})
    with pytest.raises(ErrorDeDatos, match="umbral_confirmar no puede ser mayor que umbral_lleno"):
        cargar_reglas(ruta)


def test_umbral_fuera_de_rango(tmp_path: Path) -> None:
    with pytest.raises(ErrorDeDatos, match="«umbral_lleno»"):
        cargar_reglas(_yaml_con(tmp_path, mapeo={"umbral_lleno": 1.5}))


def test_falta_un_pais(tmp_path: Path) -> None:
    ruta = _yaml_con(tmp_path, identificador_tributario={"por_pais": {"CO": "NIT", "EC": "RUC"}})
    with pytest.raises(ErrorDeDatos, match="no tiene el identificador de: PE, PA, HN"):
        cargar_reglas(ruta)


def test_clave_mal_escrita(tmp_path: Path) -> None:
    ruta = _yaml_con(tmp_path, vigencias={"dias_por_vencr": 30})
    with pytest.raises(ErrorDeDatos, match="«dias_por_vencr»: campo no reconocido"):
        cargar_reglas(ruta)


def test_dias_negativos(tmp_path: Path) -> None:
    with pytest.raises(ErrorDeDatos, match="«dias_por_vencer»"):
        cargar_reglas(_yaml_con(tmp_path, vigencias={"dias_por_vencer": -1}))


# ---------- 2. RN3 y RN6: vigencia de los soportes ----------


def test_soportes_reales_a_la_fecha_fija() -> None:
    """A la fecha fija de las pruebas (2026-09-01), con aviso desde 15 días."""
    estados = {
        e.tipo: e.estado
        for e in evaluar_soportes(list(TipoSoporte), INDICE, FECHA_FIJA, QUINCE_DIAS)
    }
    assert estados == {
        TipoSoporte.CAMARA_COMERCIO: EstadoSoporte.PRESENTE,  # vence 2026-09-30: 29 días
        TipoSoporte.RUT: EstadoSoporte.PRESENTE,  # no vence
        TipoSoporte.CERTIFICACION_BANCARIA: EstadoSoporte.PRESENTE,
        TipoSoporte.PARAFISCALES: EstadoSoporte.VENCIDO,  # venció 2026-08-31
        TipoSoporte.ESTADOS_FINANCIEROS: EstadoSoporte.PRESENTE,
        TipoSoporte.CERTIFICADO_ISO_9001: EstadoSoporte.PRESENTE,
        TipoSoporte.CERTIFICADO_CUMPLIMIENTO_TRIBUTARIO: EstadoSoporte.AUSENTE,  # no existe
    }


@pytest.mark.parametrize(
    ("fecha", "estado", "dias"),
    [
        (date(2026, 9, 1), EstadoSoporte.PRESENTE, 29),
        (date(2026, 9, 14), EstadoSoporte.PRESENTE, 16),  # un día antes del aviso
        (date(2026, 9, 15), EstadoSoporte.POR_VENCER, 15),  # justo 15 días: ya avisa
        (date(2026, 9, 30), EstadoSoporte.POR_VENCER, 0),  # vence hoy: todavía vale
        (date(2026, 10, 1), EstadoSoporte.VENCIDO, -1),  # al día siguiente, vencido
        (date(2026, 11, 24), EstadoSoporte.VENCIDO, -55),  # el día real de hoy
    ],
)
def test_camara_de_comercio_segun_la_fecha(fecha: date, estado: EstadoSoporte, dias: int) -> None:
    """La Cámara de Comercio vence el 2026-09-30 (RN7: la fecha se inyecta)."""
    e = evaluar_soporte(TipoSoporte.CAMARA_COMERCIO, INDICE, fecha, QUINCE_DIAS)
    assert e.estado is estado
    assert e.dias_restantes == dias
    assert e.archivo == "camara-comercio-2026-08.txt"
    assert e.bloquea is (estado is EstadoSoporte.VENCIDO)  # por vencer avisa, pero NO bloquea


def test_notas_en_lenguaje_claro() -> None:
    def nota(tipo: TipoSoporte, fecha: date = FECHA_FIJA) -> str:
        return evaluar_soporte(tipo, INDICE, fecha, QUINCE_DIAS).nota

    assert nota(TipoSoporte.PARAFISCALES) == "venció el 2026-08-31 (hace 1 día)"
    assert nota(TipoSoporte.RUT) == "no tiene vencimiento"
    assert nota(TipoSoporte.CERTIFICADO_CUMPLIMIENTO_TRIBUTARIO) == "no está en el repositorio"
    assert nota(TipoSoporte.CAMARA_COMERCIO, date(2026, 9, 20)) == (
        "vence el 2026-09-30: quedan 10 días (aviso desde 15)"
    )


def test_ausente_no_tiene_archivo_y_bloquea() -> None:
    e = evaluar_soporte(
        TipoSoporte.CERTIFICADO_CUMPLIMIENTO_TRIBUTARIO, INDICE, FECHA_FIJA, QUINCE_DIAS
    )
    assert e.archivo is None and e.vigencia_hasta is None and e.bloquea


@pytest.mark.parametrize(
    ("exigidos", "bloquea"),
    [
        ([TipoSoporte.CAMARA_COMERCIO, TipoSoporte.RUT], False),  # Panamá: todo vigente
        ([TipoSoporte.RUT, TipoSoporte.PARAFISCALES], True),  # Honduras: parafiscales vencido
        ([TipoSoporte.RUT, TipoSoporte.CERTIFICADO_CUMPLIMIENTO_TRIBUTARIO], True),  # ausente
        ([], False),
    ],
)
def test_que_bloquea_la_firma(exigidos: list[TipoSoporte], bloquea: bool) -> None:
    assert bloquean_firma(evaluar_soportes(exigidos, INDICE, FECHA_FIJA, QUINCE_DIAS)) is bloquea


# ---------- 3. RN2: datos bancarios ----------


@pytest.mark.parametrize(
    ("ruta", "bancario"),
    [
        ("banco.numero_cuenta", True),
        ("banco.swift", True),
        ("banco.nombre", True),
        ("nit", False),
        ("razon_social", False),
        ("contacto_financiero.email", False),  # es del área financiera, pero no es un dato bancario
    ],
)
def test_es_dato_bancario(ruta: str, bancario: bool) -> None:
    assert es_dato_bancario(ruta, REGLAS.datos_bancarios) is bancario


# ---------- 4. Cambiar el YAML cambia el resultado ----------


def test_mas_dias_de_aviso_cambian_el_estado(tmp_path: Path) -> None:
    con_30 = cargar_reglas(_yaml_con(tmp_path, vigencias={"dias_por_vencer": 30}))
    e = evaluar_soporte(TipoSoporte.CAMARA_COMERCIO, INDICE, FECHA_FIJA, con_30.vigencias)
    assert e.estado is EstadoSoporte.POR_VENCER  # con 15 días era "presente"


def test_un_umbral_mas_exigente_cambia_el_mapeo(
    contexto: Contexto, datos: Path, editar_json: EditarJson, tmp_path: Path
) -> None:
    """De punta a punta: el mismo caso, mapeado con dos reglas.yaml distintos.

    En una copia de los datos, la etiqueta "Razón social" del caso CO se escribe con un
    error ("Razon socail", 92 % parecida). Con el umbral normal (0.9) se llena sola; con
    umbral_lleno 0.95 pide confirmación. No se tocó ni una línea de código.
    """

    def con_error(celdas: object) -> object:
        lista = como_lista(celdas)
        lista[0] = {**como_dict(lista[0]), "etiqueta": "Razon socail"}
        return lista

    editar_json("casos/co-industrias-delta/plantilla-celdas.json", con_error)

    def estado_con(reglas: Path, salida: str) -> str:
        ctx = Contexto(
            datos=datos,
            salida=tmp_path / salida,
            fecha_ejecucion=contexto.fecha_ejecucion,
            reloj=contexto.reloj,
            reglas=reglas,
        )
        r = registro.ejecutar("proveedor_mapear_campos", {"caso": "co-industrias-delta"}, ctx)
        vista = json.loads(r.a_json())["data"]
        estados = {
            c["etiqueta"]: grupo
            for grupo in ("llenos", "faltantes", "requiere_confirmacion")
            for c in vista[grupo]
        }
        return estados["Razon socail"]

    exigente = _yaml_con(tmp_path, mapeo={"umbral_lleno": 0.95})
    assert estado_con(ARCHIVO_REAL, "out-normal") == "llenos"
    assert estado_con(exigente, "out-exigente") == "requiere_confirmacion"


def test_una_regla_rota_da_error_claro_en_la_herramienta(
    contexto: Contexto, tmp_path: Path
) -> None:
    roto = tmp_path / "reglas.yaml"
    roto.write_text("mapeo: [", encoding="utf-8")
    ctx = Contexto(
        datos=contexto.datos,
        salida=contexto.salida,
        fecha_ejecucion=contexto.fecha_ejecucion,
        reloj=contexto.reloj,
        reglas=roto,
    )
    r = registro.ejecutar("proveedor_mapear_campos", {"caso": "ec-corp-andina"}, ctx)
    assert not r.ok
    assert r.error is not None and "no es un YAML válido" in r.error
