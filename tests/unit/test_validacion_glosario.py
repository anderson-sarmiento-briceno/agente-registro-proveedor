"""Prueba de la revisión nueva del glosario (Paso 5): etiquetas que solo cambian en
mayúsculas, tildes o signos, pero apuntan a datos distintos. El mapeo compara sin
mayúsculas ni tildes, así que no sabría cuál usar."""

from pathlib import Path

from registro_proveedor.dominio.validacion import validar_datos
from tests.ayudas import EditarJson, como_dict


def test_etiquetas_iguales_con_datos_distintos_es_error(
    datos: Path, editar_json: EditarJson
) -> None:
    editar_json("glosario-campos.json", lambda g: {**como_dict(g), "RAZON SOCIAL": "nit"})
    errores = [h.mensaje for h in validar_datos(datos).errores]
    assert any("solo se diferencian en mayúsculas, tildes o signos" in m for m in errores)


def test_etiquetas_iguales_con_el_mismo_dato_no_es_error(
    datos: Path, editar_json: EditarJson
) -> None:
    editar_json("glosario-campos.json", lambda g: {**como_dict(g), "RAZON SOCIAL": "razon_social"})
    assert validar_datos(datos).ok
