"""Pruebas de `dominio/paquete.py`: el paquete para firma.

Cómo está organizado:
    1. Los 4 casos de referencia: listo / no listo y sus motivos (a la fecha fija).
    2. Qué bloquea y qué no: soportes vencidos o ausentes y campos por confirmar
       bloquean; un faltante o un soporte por vencer, no.
    3. RN2: el borrador del correo nunca lleva datos bancarios ni sensibles.
    4. Los archivos: formulario regenerado, soportes copiados, manifiesto con huellas,
       y el paquete viejo reemplazado entero.

`_armar("caso", ...)` mapea el caso y arma su paquete en una carpeta temporal.
"""

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from registro_proveedor.config import RAIZ_PROYECTO
from registro_proveedor.dominio.casos import leer_caso
from registro_proveedor.dominio.generadores.comun import ErrorDeGeneracion
from registro_proveedor.dominio.lectura import (
    CARPETA_SOPORTES,
    cargar_glosario,
    cargar_indice_soportes,
    cargar_maestro,
    cargar_solicitud,
    carpeta_de_caso,
)
from registro_proveedor.dominio.mapeo import Decision, Mapeo, confirmar_campo, mapear_caso
from registro_proveedor.dominio.modelos import Maestro, Solicitud
from registro_proveedor.dominio.paquete import (
    ARCHIVO_BORRADOR,
    ARCHIVO_CHECKLIST,
    ARCHIVO_MANIFIESTO,
    ErrorDePaquete,
    Paquete,
    armar_paquete,
)
from registro_proveedor.dominio.reglas import cargar_reglas
from tests.ayudas import DATOS_REALES, FECHA_FIJA, HORA_FIJA

GLOSARIO = cargar_glosario(DATOS_REALES)
MAESTRO = cargar_maestro(DATOS_REALES)
REGLAS = cargar_reglas(RAIZ_PROYECTO / "config" / "reglas.yaml")
INDICE = cargar_indice_soportes(DATOS_REALES)

# Valores que NUNCA deben aparecer en el borrador del correo.
NUMERO_CUENTA = "03100012345"
SWIFT = "COLOCOBM"
CEDULA = "71555123"
BANCO = "Bancolombia"
TIPO_CUENTA = "Ahorros"


def _mapeo(caso: str, maestro: Maestro = MAESTRO, aceptar: tuple[str, ...] = ()) -> Mapeo:
    m = mapear_caso(leer_caso(DATOS_REALES, caso), GLOSARIO, maestro, REGLAS, HORA_FIJA, FECHA_FIJA)
    for etiqueta in aceptar:
        m, _ = confirmar_campo(m, etiqueta, Decision.ACEPTAR, "analista", HORA_FIJA)
    return m


def _armar(
    caso: str,
    carpeta: Path,
    *,
    fecha: date = FECHA_FIJA,
    maestro: Maestro = MAESTRO,
    aceptar: tuple[str, ...] = (),
    solicitud: Solicitud | None = None,
    datos: Path = DATOS_REALES,
    mapeo: Mapeo | None = None,
) -> Paquete:
    return armar_paquete(
        caso=leer_caso(DATOS_REALES, caso),
        solicitud=solicitud or cargar_solicitud(carpeta_de_caso(DATOS_REALES, caso)),
        mapeo=mapeo or _mapeo(caso, maestro, aceptar),
        maestro=maestro,
        indice=INDICE,
        carpeta_soportes=datos / CARPETA_SOPORTES,
        reglas=REGLAS,
        fecha=fecha,
        generado_en=HORA_FIJA,
        carpeta_caso=carpeta,
    )


def _leer(paquete: Paquete, archivo: str) -> str:
    return (paquete.carpeta / archivo).read_text(encoding="utf-8")


# ---------- 1. Los 4 casos de referencia (fecha fija: 2026-09-01) ----------


@pytest.mark.parametrize(
    ("caso", "listo", "motivos"),
    [
        ("co-industrias-delta", True, []),
        (
            "ec-corp-andina",
            False,
            [
                "soporte ausente: Certificado de cumplimiento tributario, "
                "no está en el repositorio",
                "campo por confirmar: «RUC»",
            ],
        ),
        (
            "hn-agroexport-sula",
            False,
            [
                "soporte vencido: Certificación de parafiscales, venció el 2026-08-31 (hace 1 día)",
                "campo por confirmar: «RTN»",
            ],
        ),
        # Todos sus soportes están vigentes: lo único que bloquea es el RUC por confirmar.
        ("pa-logistica-istmo", False, ["campo por confirmar: «RUC»"]),
    ],
)
def test_casos_de_referencia(tmp_path: Path, caso: str, listo: bool, motivos: list[str]) -> None:
    paquete = _armar(caso, tmp_path)
    assert paquete.listo_para_firma is listo
    assert paquete.motivos == motivos


# ---------- 2. Qué bloquea y qué no ----------


def test_confirmar_el_pendiente_deja_el_paquete_listo(tmp_path: Path) -> None:
    """Panamá: con el RUC aceptado, ya no hay nada que bloquee."""
    paquete = _armar("pa-logistica-istmo", tmp_path, aceptar=("RUC",))
    assert paquete.listo_para_firma
    assert paquete.motivos == []


def test_un_campo_faltante_no_bloquea_pero_se_avisa(tmp_path: Path) -> None:
    sin_telefono = MAESTRO.model_copy(update={"telefono": None})
    paquete = _armar("co-industrias-delta", tmp_path, maestro=sin_telefono)
    assert paquete.listo_para_firma  # RN3: un faltante no bloquea
    assert paquete.avisos == ["campo faltante en el maestro: «Teléfono»"]


def test_un_soporte_por_vencer_no_bloquea_pero_se_avisa(tmp_path: Path) -> None:
    paquete = _armar("co-industrias-delta", tmp_path, fecha=date(2027, 2, 14))
    assert paquete.listo_para_firma  # RN6: por vencer avisa, no bloquea
    assert paquete.avisos == [
        "soporte por vencer: Cámara de Comercio, vence el 2027-02-24: "
        "quedan 10 días (aviso desde 15)"
    ]


def test_cuando_vence_la_camara_colombia_deja_de_estar_listo(tmp_path: Path) -> None:
    """RN7: por eso las pruebas usan una fecha fija. Desde el 2027-02-25 ya venció."""
    paquete = _armar("co-industrias-delta", tmp_path, fecha=date(2027, 2, 25))
    assert not paquete.listo_para_firma
    assert paquete.motivos[0].startswith("soporte vencido: Cámara de Comercio")


def test_la_columna_vence_dice_los_dias_que_faltan(tmp_path: Path) -> None:
    """Revisión de Anderson: al lado de la fecha, cuántos días faltan (o hace cuánto venció)."""
    texto = _leer(_armar("hn-agroexport-sula", tmp_path, fecha=date(2026, 11, 26)), "checklist.md")
    assert "| 2027-02-24 (faltan 90 días) |" in texto  # Cámara de Comercio
    assert "| 2026-08-31 (venció hace 87 días) |" in texto  # parafiscales


# ---------- 3. RN2: el borrador nunca lleva datos bancarios ni sensibles ----------


@pytest.mark.parametrize(
    "caso", ["co-industrias-delta", "ec-corp-andina", "hn-agroexport-sula", "pa-logistica-istmo"]
)
def test_el_borrador_no_tiene_datos_bancarios(tmp_path: Path, caso: str) -> None:
    borrador = _leer(_armar(caso, tmp_path), ARCHIVO_BORRADOR)
    for prohibido in (NUMERO_CUENTA, SWIFT, CEDULA, BANCO, TIPO_CUENTA):
        assert prohibido not in borrador, prohibido


def test_un_dato_bancario_en_el_asunto_impide_armar_el_paquete(tmp_path: Path) -> None:
    """Segunda protección: aunque llegue por otro lado (el correo del cliente), no pasa."""
    solicitud = cargar_solicitud(carpeta_de_caso(DATOS_REALES, "co-industrias-delta"))
    con_cuenta = solicitud.model_copy(update={"asunto": f"Registro (cuenta {NUMERO_CUENTA})"})
    with pytest.raises(ErrorDePaquete, match=r"«banco\.numero_cuenta».*RN2"):
        _armar("co-industrias-delta", tmp_path, solicitud=con_cuenta)
    # El mensaje no muestra el dato, y no queda ningún paquete (ni a medias).
    assert list(tmp_path.iterdir()) == []


def test_el_titular_igual_a_la_razon_social_no_es_secreto(tmp_path: Path) -> None:
    """El titular de la cuenta es "Empresa Ejemplo S.A.S.", que va en la firma del correo."""
    borrador = _leer(_armar("co-industrias-delta", tmp_path), ARCHIVO_BORRADOR)
    assert borrador.rstrip().endswith("Empresa Ejemplo S.A.S.")


def test_borrador_listo_y_no_listo(tmp_path: Path) -> None:
    listo = _leer(_armar("co-industrias-delta", tmp_path / "co"), ARCHIVO_BORRADOR)
    assert listo.startswith(
        "Para: compras@industrias-delta-ficticia.com\n"
        "Asunto: Re: Solicitud de registro como proveedor - Empresa Ejemplo\n"
    )
    assert "NO ENVIAR" not in listo
    assert "Adjuntamos el formulario de registro de proveedor de Empresa Ejemplo S.A.S." in listo
    assert "- Registro Único Tributario\n" in listo

    no_listo = _leer(_armar("hn-agroexport-sula", tmp_path / "hn"), ARCHIVO_BORRADOR)
    assert "**BORRADOR · NO ENVIAR TODAVÍA.**" in no_listo


def test_borrador_de_portal(tmp_path: Path) -> None:
    borrador = _leer(_armar("pa-logistica-istmo", tmp_path), ARCHIVO_BORRADOR)
    assert (
        "completamos el registro de Empresa Ejemplo S.A.S. como proveedor en su portal" in borrador
    )


# ---------- 4. Los archivos del paquete ----------


def test_archivos_del_paquete(tmp_path: Path) -> None:
    paquete = _armar("hn-agroexport-sula", tmp_path)
    assert paquete.carpeta == tmp_path / "paquete"
    esperados = [
        "formulario.xlsx",
        "camara-comercio-2026-11.txt",
        "rut-2026.txt",
        "parafiscales-2026-07.txt",  # vencido, pero se copia para saber cuál renovar
        ARCHIVO_CHECKLIST,
        ARCHIVO_BORRADOR,
        ARCHIVO_MANIFIESTO,
    ]
    assert paquete.archivos == esperados
    assert sorted(p.name for p in paquete.carpeta.iterdir()) == sorted(esperados)
    # La carpeta temporal desapareció.
    assert [p.name for p in tmp_path.iterdir()] == ["paquete"]


def test_un_soporte_ausente_no_se_copia(tmp_path: Path) -> None:
    paquete = _armar("ec-corp-andina", tmp_path)
    assert "formulario.pdf" in paquete.archivos
    assert len([a for a in paquete.archivos if a.endswith(".txt")]) == 4  # de 5 exigidos


def test_los_soportes_copiados_son_iguales_al_original(tmp_path: Path) -> None:
    paquete = _armar("co-industrias-delta", tmp_path)
    original = DATOS_REALES / CARPETA_SOPORTES / "rut-2026.txt"
    assert (paquete.carpeta / "rut-2026.txt").read_bytes() == original.read_bytes()


def test_checklist(tmp_path: Path) -> None:
    texto = _leer(_armar("hn-agroexport-sula", tmp_path), ARCHIVO_CHECKLIST)
    assert "## ⛔ No está listo para firma" in texto
    assert "- [ ] campo por confirmar: «RTN»" in texto
    # Piloto (Paso 21): la etiqueta no está en el glosario, así que no se puede decir que
    # "falta en el maestro": puede estar con otro nombre.
    assert "- etiqueta no reconocida: «Referencias comerciales»" in texto
    assert (
        "| Certificación de parafiscales | ⛔ vencido | 2026-08-31 (venció hace 1 día) | "
        "Renovarlo antes de firmar |" in texto
    )
    assert "| RUT | ✅ vigente | — | Nada | no tiene vencimiento |" in texto
    # El formato del formulario, en palabras (no "xlsx").
    assert "Formulario del cliente: Excel (se genera formulario.xlsx)" in texto
    assert "\n\n\n" not in texto  # sin líneas en blanco de más


def test_checklist_listo(tmp_path: Path) -> None:
    texto = _leer(_armar("co-industrias-delta", tmp_path), ARCHIVO_CHECKLIST)
    assert "## ✅ Listo para firma" in texto
    assert "Antes de firmar" not in texto


def test_manifiesto(tmp_path: Path) -> None:
    paquete = _armar("pa-logistica-istmo", tmp_path, aceptar=("RUC",))
    texto = _leer(paquete, ARCHIVO_MANIFIESTO)
    manifiesto = json.loads(texto)
    assert manifiesto["listo_para_firma"] is True
    assert manifiesto["fecha_ejecucion"] == "2026-09-01"
    assert manifiesto["version_maestro"] == "sin versión"

    # El origen de cada campo, con quién confirmó.
    ruc = next(c for c in manifiesto["campos"] if c["etiqueta"] == "RUC")
    assert (ruc["ruta"], ruc["decision"], ruc["confirmado_por"]) == ("nit", "aceptar", "analista")

    # La huella de cada archivo coincide con su contenido.
    for archivo in manifiesto["archivos"]:
        contenido = (paquete.carpeta / archivo["nombre"]).read_bytes()
        assert archivo["sha256"] == hashlib.sha256(contenido).hexdigest()
        assert archivo["bytes"] == len(contenido)

    # Sin valores: esos están en el formulario.
    for valor in (NUMERO_CUENTA, CEDULA, "900123456"):
        assert valor not in texto


def test_el_paquete_viejo_se_reemplaza_entero(tmp_path: Path) -> None:
    primero = _armar("co-industrias-delta", tmp_path)
    (primero.carpeta / "archivo-viejo.txt").write_text("de una versión anterior", encoding="utf-8")
    segundo = _armar("co-industrias-delta", tmp_path)
    assert not (segundo.carpeta / "archivo-viejo.txt").exists()


# ---------- Errores ----------


def test_falta_el_archivo_de_un_soporte(tmp_path: Path, datos: Path) -> None:
    (datos / CARPETA_SOPORTES / "rut-2026.txt").unlink()
    with pytest.raises(
        ErrorDePaquete, match=r"no se encontró el archivo «rut-2026\.txt» del soporte RUT"
    ):
        _armar("co-industrias-delta", tmp_path / "salida", datos=datos)
    assert not (tmp_path / "salida" / "paquete").exists()


def test_mapeo_de_otra_plantilla(tmp_path: Path) -> None:
    with pytest.raises(ErrorDeGeneracion, match="no corresponde a la plantilla actual"):
        _armar("co-industrias-delta", tmp_path, mapeo=_mapeo("hn-agroexport-sula"))
