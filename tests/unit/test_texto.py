"""Pruebas de `dominio/texto.py`: normalizar textos para compararlos."""

import pytest

from registro_proveedor.dominio.texto import normalizar, palabras


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Panamá", "panama"),
        ("PANAMÁ", "panama"),
        ("Razón social:", "razon social"),  # el ":" final desaparece
        ("Departamento / Provincia", "departamento provincia"),
        ("  Número   de  cuenta ", "numero de cuenta"),  # espacios de más
        ("ec-corp-andina", "ec corp andina"),
        ("Compañía", "compania"),  # la ñ queda como n
        ("S.A.S.", "s a s"),
        ("", ""),
    ],
)
def test_normalizar(texto: str, esperado: str) -> None:
    assert normalizar(texto) == esperado


def test_palabras() -> None:
    assert palabras("Corporación Andina de Servicios S.A.") == [
        "corporacion",
        "andina",
        "de",
        "servicios",
        "s",
        "a",
    ]
