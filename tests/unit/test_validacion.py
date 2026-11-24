"""Pruebas de la validación completa de `datos/`: errores, sugerencias y reporte."""

import hashlib
import shutil
from pathlib import Path

from registro_proveedor.dominio.validacion import (
    Nivel,
    Reporte,
    formatear_reporte,
    validar_datos,
)
from tests.ayudas import DATOS_REALES, EditarJson, como_dict, como_lista


def _mensajes(reporte: Reporte, nivel: Nivel) -> str:
    return "\n".join(f"{h.archivo}: {h.mensaje}" for h in reporte.hallazgos if h.nivel is nivel)


# ---------- Datos reales ----------


def test_datos_reales_sin_errores_y_con_la_sugerencia_de_version() -> None:
    reporte = validar_datos(DATOS_REALES)
    assert reporte.ok, _mensajes(reporte, Nivel.ERROR)
    assert len(reporte.sugerencias) == 1
    sugerencia = reporte.sugerencias[0]
    assert sugerencia.archivo == "datos/repositorio/maestro.json"
    assert "version" in sugerencia.mensaje and "actualizado_en" in sugerencia.mensaje


def test_validar_no_modifica_datos() -> None:
    antes = _huella(DATOS_REALES)
    validar_datos(DATOS_REALES)
    assert _huella(DATOS_REALES) == antes


def _huella(carpeta: Path) -> dict[str, str]:
    return {
        p.relative_to(carpeta).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(carpeta.rglob("*"))
        if p.is_file()
    }


# ---------- Errores: el dato está roto ----------


def test_id_distinto_a_la_carpeta(datos: Path, editar_json: EditarJson) -> None:
    editar_json(
        "casos/co-industrias-delta/solicitud.json",
        lambda s: {**como_dict(s), "id": "otro-id"},
    )
    reporte = validar_datos(datos)
    assert "el id «otro-id» no coincide con el nombre de la carpeta" in _mensajes(
        reporte, Nivel.ERROR
    )


def test_excel_sin_plantilla_de_celdas(datos: Path) -> None:
    (datos / "casos/co-industrias-delta/plantilla-celdas.json").unlink()
    reporte = validar_datos(datos)
    errores = _mensajes(reporte, Nivel.ERROR)
    assert "co-industrias-delta/plantilla-celdas.json: no existe el archivo" in errores


def test_pdf_sin_plantilla_de_campos(datos: Path) -> None:
    (datos / "casos/ec-corp-andina/plantilla-campos.json").unlink()
    reporte = validar_datos(datos)
    assert "ec-corp-andina/plantilla-campos.json: no existe el archivo" in _mensajes(
        reporte, Nivel.ERROR
    )


def test_celda_repetida_en_la_misma_hoja(datos: Path, editar_json: EditarJson) -> None:
    def repetir(celdas: object) -> object:
        lista = como_lista(celdas)
        lista[1] = {**como_dict(lista[1]), "celda_valor": "C3"}  # C3 ya es el valor del elemento 1
        return lista

    editar_json("casos/co-industrias-delta/plantilla-celdas.json", repetir)
    reporte = validar_datos(datos)
    assert "elemento 2: la celda C3 de la hoja «Datos Proveedor» ya la usa el elemento 1" in (
        _mensajes(reporte, Nivel.ERROR)
    )


def test_misma_celda_en_otra_hoja_no_es_error() -> None:
    # En el caso CO, "B3" se usa en "Datos Proveedor" y en "Datos Bancarios".
    assert validar_datos(DATOS_REALES).ok


def test_ruta_de_glosario_inexistente(datos: Path, editar_json: EditarJson) -> None:
    editar_json("glosario-campos.json", lambda g: {**como_dict(g), "SWIFT": "banco.swiftt"})
    reporte = validar_datos(datos)
    assert "«SWIFT» → «banco.swiftt»: no existe «swiftt» en el maestro dentro de «banco»" in (
        _mensajes(reporte, Nivel.ERROR)
    )


def test_ruta_de_glosario_a_un_grupo(datos: Path, editar_json: EditarJson) -> None:
    editar_json("glosario-campos.json", lambda g: {**como_dict(g), "Banco": "banco"})
    reporte = validar_datos(datos)
    assert "apunta a un grupo de datos, no a un valor" in _mensajes(reporte, Nivel.ERROR)


def test_ruta_de_glosario_que_atraviesa_un_valor(datos: Path, editar_json: EditarJson) -> None:
    editar_json("glosario-campos.json", lambda g: {**como_dict(g), "NIT": "nit.numero"})
    reporte = validar_datos(datos)
    assert "«nit» es un valor, no un grupo" in _mensajes(reporte, Nivel.ERROR)


def test_archivo_de_soporte_ausente(datos: Path) -> None:
    (datos / "repositorio/soportes/rut-2026.txt").unlink()
    reporte = validar_datos(datos)
    assert "no existe el archivo «rut-2026.txt»" in _mensajes(reporte, Nivel.ERROR)


def test_tipo_de_soporte_repetido(datos: Path, editar_json: EditarJson) -> None:
    def repetir(indice: object) -> object:
        lista = como_lista(indice)
        lista[1] = {**como_dict(lista[1]), "tipo": "camara_comercio"}
        return lista

    editar_json("repositorio/soportes/index.json", repetir)
    reporte = validar_datos(datos)
    assert "el tipo «camara_comercio» está repetido" in _mensajes(reporte, Nivel.ERROR)


def test_carpeta_de_caso_con_nombre_invalido(datos: Path) -> None:
    shutil.copytree(datos / "casos/co-industrias-delta", datos / "casos/Caso Nuevo")
    reporte = validar_datos(datos)
    assert "el nombre de caso «Caso Nuevo» no es válido" in _mensajes(reporte, Nivel.ERROR)


def test_un_caso_roto_no_impide_revisar_los_demas(datos: Path) -> None:
    (datos / "casos/co-industrias-delta/solicitud.json").write_text("{roto", encoding="utf-8")
    (datos / "casos/hn-agroexport-sula/plantilla-celdas.json").unlink()
    reporte = validar_datos(datos)
    errores = _mensajes(reporte, Nivel.ERROR)
    assert "co-industrias-delta/solicitud.json: no es un JSON válido" in errores
    assert "hn-agroexport-sula/plantilla-celdas.json: no existe el archivo" in errores
    assert "ec-corp-andina" not in errores


def test_carpeta_de_datos_inexistente(tmp_path: Path) -> None:
    reporte = validar_datos(tmp_path / "no-existe")
    assert not reporte.ok
    assert "no existe la carpeta de datos" in _mensajes(reporte, Nivel.ERROR)


# ---------- Sugerencias: el dato funciona, pero se puede mejorar ----------


def test_maestro_con_campo_desconocido_es_sugerencia(datos: Path, editar_json: EditarJson) -> None:
    def agregar(m: object) -> object:
        d = como_dict(m)
        d["regimen_simple"] = True
        d["banco"] = {**como_dict(d["banco"]), "sucursal": "Centro"}
        return d

    editar_json("repositorio/maestro.json", agregar)
    reporte = validar_datos(datos)
    assert reporte.ok
    sugerencias = _mensajes(reporte, Nivel.SUGERENCIA)
    assert "el campo «regimen_simple» no está en el modelo del maestro" in sugerencias
    assert "el campo «banco.sucursal» no está en el modelo del maestro" in sugerencias


def test_maestro_con_campo_conocido_vacio_es_sugerencia(
    datos: Path, editar_json: EditarJson
) -> None:
    editar_json(
        "repositorio/maestro.json",
        lambda m: {k: v for k, v in como_dict(m).items() if k != "telefono"},
    )
    reporte = validar_datos(datos)
    assert reporte.ok  # la ruta "Teléfono" → "telefono" del glosario no es un error
    assert "telefono" in _mensajes(reporte, Nivel.SUGERENCIA)


def test_portal_sin_plantilla_es_sugerencia(datos: Path) -> None:
    (datos / "casos/pa-logistica-istmo/plantilla-campos.json").unlink()
    reporte = validar_datos(datos)
    assert reporte.ok
    assert "el caso es de portal y no tiene plantilla-campos.json" in _mensajes(
        reporte, Nivel.SUGERENCIA
    )


def test_soporte_fuera_del_indice_es_sugerencia(datos: Path) -> None:
    (datos / "repositorio/soportes/olvidado.txt").write_text("x", encoding="utf-8")
    reporte = validar_datos(datos)
    assert reporte.ok
    assert "olvidado.txt: el archivo no está en index.json" in _mensajes(reporte, Nivel.SUGERENCIA)


# ---------- Reporte ----------


def test_formato_del_reporte() -> None:
    texto = formatear_reporte(validar_datos(DATOS_REALES))
    assert texto.startswith("Validación de datos/")
    assert "ERRORES (0)" in texto
    assert "SUGERENCIAS (1)" in texto
    assert texto.endswith("Resultado: OK · 0 errores · 1 sugerencia")
