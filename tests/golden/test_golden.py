"""Pruebas golden: el resultado de la demo, caso por caso, comparado con lo guardado.

¿Qué es una prueba "golden"?
    Se guarda en el repositorio cómo DEBE quedar cada caso (su mapeo, su checklist, su
    borrador, las celdas de su Excel, el texto de su PDF...). La prueba ejecuta la demo
    y compara. Si un cambio altera algo sin querer, la prueba falla y muestra la
    diferencia línea por línea.

¿Y si el cambio es intencional?
    `uv run pytest --actualizar-golden` reescribe los archivos de `tests/golden/`. El
    cambio queda a la vista en git (`git diff tests/golden`) y se revisa antes de aceptarlo.

Para que la comparación sea justa en cualquier máquina (Windows o Linux):
    - todo se lee como texto con saltos de línea "\\n";
    - el Excel se compara por sus CELDAS (valor, color y comentario), no por sus bytes;
    - el PDF, por su TEXTO;
    - del manifiesto se quitan las huellas de los archivos binarios: la compresión
      puede variar entre sistemas. Que las huellas no cambien entre dos ejecuciones en
      la misma máquina lo comprueba test_demo.py.
"""

import difflib
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from registro_proveedor.demo import ejecutar_demo
from tests.ayudas import DATOS_REALES, FECHA_FIJA

GOLDEN = Path(__file__).parent
CASOS = ["co-industrias-delta", "ec-corp-andina", "hn-agroexport-sula", "pa-logistica-istmo"]


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str, str]:
    """Ejecuta la demo UNA vez para todas las pruebas de este archivo (scope="module").

    Devuelve (carpeta de salida, resumen, matriz de llamadas).
    """
    salida = tmp_path_factory.mktemp("golden") / "out"
    resultado = ejecutar_demo(DATOS_REALES, salida, FECHA_FIJA)
    assert resultado.codigo == 0, resultado.texto
    return salida, resultado.texto + "\n", resultado.matriz + "\n"


# ---------- Las pruebas ----------


def test_resumen_de_la_demo(demo: tuple[Path, str, str], actualizar_golden: bool) -> None:
    _comparar("demo.txt", demo[1], actualizar_golden)


def test_matriz_de_llamadas(demo: tuple[Path, str, str], actualizar_golden: bool) -> None:
    """Casos por herramientas: qué llamó la demo y qué respondió cada herramienta."""
    _comparar("llamadas.md", demo[2], actualizar_golden)


@pytest.mark.parametrize("caso", CASOS)
def test_caso(demo: tuple[Path, str, str], caso: str, actualizar_golden: bool) -> None:
    fallas = [
        falla
        for nombre, actual in _instantanea(demo[0], caso).items()
        if (falla := _comparar(f"{caso}/{nombre}", actual, actualizar_golden, fallar=False))
    ]
    if fallas:
        pytest.fail("\n\n".join(fallas), pytrace=False)


def test_no_hay_golden_sobrantes(actualizar_golden: bool) -> None:
    """Si un caso deja de existir, su carpeta de golden también debe borrarse."""
    carpetas = {p.name for p in GOLDEN.iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert carpetas == set(CASOS)


# ---------- Qué se compara de cada caso ----------


def _instantanea(salida: Path, caso: str) -> dict[str, str]:
    """Los textos que se comparan de un caso: nombre del golden → contenido actual."""
    paquete = salida / caso / "paquete"
    textos = {
        "mapeo.json": (salida / caso / "mapeo.json").read_text(encoding="utf-8"),
        "checklist.md": (paquete / "checklist.md").read_text(encoding="utf-8"),
        "borrador-correo.md": (paquete / "borrador-correo.md").read_text(encoding="utf-8"),
        "manifiesto.json": _manifiesto_sin_huellas_binarias(paquete / "manifiesto.json"),
    }
    if (paquete / "formulario.xlsx").exists():
        textos["celdas-excel.json"] = _celdas_excel(paquete / "formulario.xlsx")
    if (paquete / "formulario.pdf").exists():
        textos["texto-pdf.txt"] = _texto_pdf(paquete / "formulario.pdf")
    if (paquete / "valores-portal.md").exists():
        textos["valores-portal.md"] = (paquete / "valores-portal.md").read_text(encoding="utf-8")
    return textos


def _celdas_excel(ruta: Path) -> str:
    """Cada hoja y cada celda con contenido: su valor, su color de fondo y su comentario."""
    libro = load_workbook(ruta)
    hojas: dict[str, dict[str, dict[str, object]]] = {}
    for hoja in libro.worksheets:
        celdas: dict[str, dict[str, object]] = {}
        for fila in hoja.iter_rows():
            for celda in fila:
                relleno = str(celda.fill.fgColor.rgb)[-6:] if celda.fill.fill_type else None
                comentario = celda.comment.text if celda.comment else None
                if celda.value is None and relleno is None and comentario is None:
                    continue
                celdas[celda.coordinate] = {
                    "valor": celda.value,
                    "tipo": celda.data_type,
                    "relleno": relleno,
                    "comentario": comentario,
                }
        hojas[hoja.title] = celdas
    return json.dumps(hojas, ensure_ascii=False, indent=2) + "\n"


def _texto_pdf(ruta: Path) -> str:
    return "\n".join(pagina.extract_text() for pagina in PdfReader(ruta).pages) + "\n"


def _manifiesto_sin_huellas_binarias(ruta: Path) -> str:
    manifiesto = json.loads(ruta.read_text(encoding="utf-8"))
    for archivo in manifiesto["archivos"]:
        if archivo["nombre"].endswith((".xlsx", ".pdf")):
            archivo["sha256"] = "(binario: se comprueba en test_demo.py)"
            archivo["bytes"] = None
    return json.dumps(manifiesto, ensure_ascii=False, indent=2) + "\n"


# ---------- Comparar (o actualizar) ----------


def _comparar(nombre: str, actual: str, actualizar: bool, fallar: bool = True) -> str | None:
    """Compara con `tests/golden/<nombre>`. Devuelve el mensaje de falla, o None si coincide."""
    ruta = GOLDEN / nombre
    if actualizar:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(actual, encoding="utf-8", newline="\n")
        return None
    if not ruta.exists():
        mensaje = f"falta el golden {nombre}: ejecute `uv run pytest --actualizar-golden`"
    else:
        # `read_text` convierte "\r\n" en "\n": así no importa cómo lo guardó git.
        esperado = ruta.read_text(encoding="utf-8")
        if actual == esperado:
            return None
        diferencia = difflib.unified_diff(
            esperado.splitlines(), actual.splitlines(), "esperado", "actual", lineterm=""
        )
        mensaje = f"{nombre} cambió:\n" + "\n".join(diferencia)
    if fallar:
        pytest.fail(mensaje, pytrace=False)
    return mensaje
