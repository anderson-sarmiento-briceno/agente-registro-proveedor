"""Pruebas de las herramientas reales (`herramientas/proveedor.py`), como las llamará el agente.

Aquí no se repiten las pruebas de la lógica (eso está en test_casos.py). Se comprueba
lo propio de la herramienta: que esté registrada con su descripción, que responda
`ok=True/False` sin lanzar, que su mensaje de error ayude al agente a seguir y que
deje su línea en log.jsonl.
"""

import json
from pathlib import Path

from registro_proveedor.herramientas.base import Contexto
from registro_proveedor.herramientas.proveedor import AYUDA_CASO, registro


def _log(contexto: Contexto) -> list[dict[str, object]]:
    texto = (contexto.salida / "log.jsonl").read_text(encoding="utf-8")
    return [json.loads(linea) for linea in texto.splitlines()]


def test_herramientas_registradas() -> None:
    nombres = [h.nombre for h in registro.listar()]
    assert nombres == [
        "proveedor_armar_paquete",
        "proveedor_confirmar_campo",
        "proveedor_generar_formulario",
        "proveedor_leer_solicitud",
        "proveedor_listar_casos",
        "proveedor_mapear_campos",
        "proveedor_registrar_envio",
    ]
    for h in registro.listar():
        assert h.descripcion  # el modelo decide con esta frase cuándo usarla
    # Solo confirmar un campo y "enviar" necesitan aprobación humana: son las únicas
    # que deciden algo o salen hacia afuera.
    con_aprobacion = [h.nombre for h in registro.listar() if h.requiere_confirmacion]
    assert con_aprobacion == ["proveedor_confirmar_campo", "proveedor_registrar_envio"]


# ---------- proveedor_listar_casos ----------


def test_listar_sin_filtro(contexto: Contexto) -> None:
    resultado = registro.ejecutar("proveedor_listar_casos", {}, contexto)
    assert resultado.ok
    datos = json.loads(resultado.a_json())["data"]
    assert len(datos["casos"]) == 4
    assert _log(contexto)[0]["resumen"] == "4 casos"


def test_listar_con_filtro(contexto: Contexto) -> None:
    resultado = registro.ejecutar("proveedor_listar_casos", {"filtro": "Ecuador"}, contexto)
    datos = json.loads(resultado.a_json())["data"]
    assert [c["caso"] for c in datos["casos"]] == ["ec-corp-andina"]
    assert _log(contexto)[0]["resumen"] == "1 caso con el filtro «Ecuador»"


def test_listar_con_filtro_demasiado_largo(contexto: Contexto) -> None:
    resultado = registro.ejecutar("proveedor_listar_casos", {"filtro": "x" * 101}, contexto)
    assert not resultado.ok
    assert resultado.error is not None and "demasiado largo" in resultado.error


def test_listar_sin_carpeta_de_casos(contexto: Contexto, tmp_path: Path) -> None:
    vacio = Contexto(
        datos=tmp_path / "vacio",
        salida=contexto.salida,
        fecha_ejecucion=contexto.fecha_ejecucion,
        reloj=contexto.reloj,
    )
    resultado = registro.ejecutar("proveedor_listar_casos", {}, vacio)
    assert not resultado.ok
    assert resultado.error is not None and "no existe la carpeta de casos" in resultado.error


# ---------- proveedor_leer_solicitud ----------


def test_leer_solicitud(contexto: Contexto) -> None:
    resultado = registro.ejecutar("proveedor_leer_solicitud", {"caso": "ec-corp-andina"}, contexto)
    assert resultado.ok
    datos = json.loads(resultado.a_json())["data"]
    assert datos["pais"] == "EC"
    assert datos["formato"] == "pdf"
    assert len(datos["campos"]) == 15
    linea = _log(contexto)[0]
    assert linea["caso"] == "ec-corp-andina"
    assert linea["resumen"] == "EC · pdf · 15 campos · 5 soportes exigidos"
    # También quedó en el log del caso.
    assert (contexto.salida / "ec-corp-andina" / "log.jsonl").is_file()


def test_caso_inexistente_sugiere_listar(contexto: Contexto) -> None:
    resultado = registro.ejecutar("proveedor_leer_solicitud", {"caso": "el-de-peru"}, contexto)
    assert not resultado.ok
    assert resultado.error == f"no existe el caso «el-de-peru». {AYUDA_CASO}"


def test_nombre_de_caso_peligroso(contexto: Contexto) -> None:
    resultado = registro.ejecutar("proveedor_leer_solicitud", {"caso": "../datos"}, contexto)
    assert not resultado.ok
    assert resultado.error is not None and resultado.error.startswith("argumentos no válidos")


def test_plantilla_corrupta_da_un_error_claro(contexto: Contexto, datos: Path) -> None:
    (datos / "casos/co-industrias-delta/plantilla-celdas.json").write_text("[", encoding="utf-8")
    roto = Contexto(
        datos=datos,
        salida=contexto.salida,
        fecha_ejecucion=contexto.fecha_ejecucion,
        reloj=contexto.reloj,
    )
    resultado = registro.ejecutar("proveedor_leer_solicitud", {"caso": "co-industrias-delta"}, roto)
    assert not resultado.ok
    assert resultado.error == (
        "datos/casos/co-industrias-delta/plantilla-celdas.json: "
        "no es un JSON válido (línea 1, columna 2)"
    )
