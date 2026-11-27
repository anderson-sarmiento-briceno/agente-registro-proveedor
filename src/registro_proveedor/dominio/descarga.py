"""El paquete de un caso como un .zip de PDF, para descargarlo desde el chat de la demo.

¿Por qué? (Paso 19)
    En la demo publicada (Render) nadie puede entrar a las carpetas del servidor: `out/`
    no se sirve a internet y se borra cuando el servicio se apaga. Para que quien prueba
    la demo VEA el resultado, el chat ofrece "Descargar paquete (.zip)".

¿Por qué PDF? (pedido de Anderson)
    El paquete del sistema está en formatos técnicos (.md, .json, .txt) que necesitan la
    auditoría y una futura base de datos, pero que una persona sin conocimientos técnicos
    no sabe abrir. La descarga los convierte en PDF. Los archivos del sistema NO cambian.

Qué lleva el zip (en una carpeta con el nombre del caso):
    1. Resumen del caso.pdf          ¿listo para firma?, qué falta, soportes y campos
    2. Formulario (vista demo).pdf   los campos con sus valores; lo sensible ENMASCARADO
    3. Borrador del correo.pdf       la respuesta para el cliente
    4. Constancia de envío.pdf       solo si ya se registró el envío
    5. De dónde salió cada dato.pdf  la trazabilidad (sale del manifiesto)
    Soportes/<nombre>.pdf            cada soporte copiado al paquete

El formulario va como una VISTA en PDF, sea cual sea el formato del cliente (Excel, PDF
o portal), con la cuenta bancaria y la identificación enmascaradas: la demo es una
página abierta (D65, D68). El formulario real, con los valores completos, se queda en el
sistema. Una prueba revisa que la cuenta completa no aparezca en ningún archivo del zip.

En producción esto no sería una descarga desde el chat: el paquete quedaría guardado
en un repositorio documental, con seguimiento y trazabilidad (SOLUCION.md, B9 y C3).
"""

import io
import zipfile
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from registro_proveedor.dominio.envio import ARCHIVO_ENVIO
from registro_proveedor.dominio.generadores.portal import valores_para_copiar
from registro_proveedor.dominio.lectura import ErrorDeDatos
from registro_proveedor.dominio.mapeo import Estado, Mapeo, Metodo, cargar_mapeo
from registro_proveedor.dominio.modelos import NOMBRES_PAIS, NOMBRES_SOPORTE
from registro_proveedor.dominio.paquete import (
    ARCHIVO_BORRADOR,
    ARCHIVO_MANIFIESTO,
    CARPETA_PAQUETE,
    QUE_HACER,
    Manifiesto,
    vence,
)
from registro_proveedor.dominio.pdf_legible import (
    AMARILLO,
    NARANJA,
    ROJO,
    VERDE,
    Celda,
    Color,
    DocumentoPdf,
    desde_markdown,
)
from registro_proveedor.dominio.reglas import EstadoSoporte, EvaluacionSoporte

RESUMEN = "1. Resumen del caso.pdf"
FORMULARIO = "2. Formulario (vista demo).pdf"
BORRADOR = "3. Borrador del correo.pdf"
CONSTANCIA = "4. Constancia de envío.pdf"
TRAZABILIDAD = "5. De dónde salió cada dato.pdf"
CARPETA_SOPORTES = "Soportes"

# Los estados, en palabras y con el color de siempre (verde bien, amarillo/naranja
# atención, rojo bloquea).
ESTADO_SOPORTE: dict[EstadoSoporte, tuple[str, Color]] = {
    EstadoSoporte.PRESENTE: ("Vigente", VERDE),
    EstadoSoporte.POR_VENCER: ("Por vencer", AMARILLO),
    EstadoSoporte.VENCIDO: ("Vencido", ROJO),
    EstadoSoporte.AUSENTE: ("Ausente", ROJO),
}
ESTADO_CAMPO: dict[Estado, tuple[str, Color | None]] = {
    Estado.LLENO: ("Lleno", None),
    Estado.FALTANTE: ("Falta en el maestro", AMARILLO),
    Estado.REQUIERE_CONFIRMACION: ("Por confirmar", NARANJA),
}
COMO_SE_ENCONTRO = {
    Metodo.GLOSARIO_EXACTO: "Igual a una etiqueta conocida",
    Metodo.GLOSARIO_NORMALIZADO: "Igual, sin contar tildes ni mayúsculas",
    Metodo.SIMILITUD: "Parecida a una etiqueta conocida",
    Metodo.SIN_COINCIDENCIA: "No se encontró en el glosario",
}


def zip_del_paquete(carpeta_caso: Path, *, formato_nombre: str | None = None) -> bytes | None:
    """El zip de PDF del paquete del caso, en memoria. None si todavía no se armó.

    `formato_nombre`: cómo se llama el formato del cliente ("Excel (…)"), para decirlo
    en el resumen y en la vista del formulario.
    """
    paquete = carpeta_caso / CARPETA_PAQUETE
    try:
        manifiesto = Manifiesto.model_validate_json(
            (paquete / ARCHIVO_MANIFIESTO).read_text(encoding="utf-8")
        )
        mapeo = cargar_mapeo(carpeta_caso)
    except (OSError, ValidationError, ErrorDeDatos):
        return None  # sin paquete (o dañado): no hay nada que descargar
    caso = manifiesto.caso

    documentos: dict[str, bytes] = {RESUMEN: _resumen(manifiesto, mapeo, formato_nombre)}
    if mapeo is not None:
        documentos[FORMULARIO] = _formulario(mapeo, manifiesto.cliente, formato_nombre)
    borrador = paquete / ARCHIVO_BORRADOR
    if borrador.is_file():
        documentos[BORRADOR] = _desde_md(
            "Borrador del correo al cliente", manifiesto, borrador, es_borrador=True
        )
    constancia = carpeta_caso / ARCHIVO_ENVIO
    if constancia.is_file():
        documentos[CONSTANCIA] = _desde_md("Constancia de envío", manifiesto, constancia)
    documentos[TRAZABILIDAD] = _trazabilidad(manifiesto)
    for soporte in manifiesto.soportes:
        archivo = paquete / soporte.archivo if soporte.archivo else None
        if archivo is not None and archivo.is_file():
            documentos[f"{CARPETA_SOPORTES}/{NOMBRES_SOPORTE[soporte.tipo]}.pdf"] = _soporte(
                soporte, archivo
            )

    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", compression=zipfile.ZIP_DEFLATED) as destino:
        for nombre, contenido in documentos.items():
            destino.writestr(f"{caso}/{nombre}", contenido)
    return memoria.getvalue()


# ---------- 1. Resumen ----------


def _resumen(manifiesto: Manifiesto, mapeo: Mapeo | None, formato_nombre: str | None) -> bytes:
    doc = DocumentoPdf(
        f"Resumen del caso · {manifiesto.cliente}",
        f"Caso {manifiesto.caso} · revisado al {manifiesto.fecha_ejecucion.isoformat()}",
    )
    if manifiesto.listo_para_firma:
        doc.recuadro("Listo para firma: Sí", VERDE)
    else:
        doc.recuadro("Todavía NO está listo para firma", ROJO)
        doc.seccion("Qué falta antes de firmar")
        doc.vinetas([m[:1].upper() + m[1:] for m in manifiesto.motivos])
    avisos = [
        f"{NOMBRES_SOPORTE[s.tipo]}: {s.nota}"
        for s in manifiesto.soportes
        if s.estado is EstadoSoporte.POR_VENCER
    ]
    faltantes = [c.etiqueta for c in manifiesto.campos if c.estado is Estado.FALTANTE]
    avisos += [f"Falta en el maestro de la empresa: «{e}»" for e in faltantes]
    if avisos:
        doc.seccion("Para tener en cuenta (no bloquea)")
        doc.vinetas(avisos)
    if formato_nombre:
        doc.parrafo(f"Formulario del cliente: {formato_nombre}")

    doc.seccion(f"Soportes que exige el cliente ({len(manifiesto.soportes)})")
    doc.tabla(
        ["Soporte", "Estado", "Vence", "Qué hacer"],
        [_fila_soporte(s) for s in manifiesto.soportes],
        anchos=(30, 18, 18, 44),
    )

    doc.seccion("Campos del formulario")
    filas: list[list[Celda]] = []
    for estado, (texto, color) in ESTADO_CAMPO.items():
        campos = [c.etiqueta for c in manifiesto.campos if c.estado is estado]
        filas.append([(texto, color), str(len(campos)), ", ".join(campos) or "ninguno"])
    doc.tabla(["Estado", "Cantidad", "Cuáles"], filas, anchos=(25, 15, 70))

    doc.seccion("Qué hay en esta descarga")
    doc.vinetas(
        [
            "Este resumen.",
            "El formulario con sus valores (vista de la demostración: la cuenta bancaria y la "
            "identificación van enmascaradas).",
            "El borrador del correo para responderle al cliente.",
            "La constancia de envío, si ya se registró.",
            "De dónde salió cada dato del formulario.",
            "Los soportes, en la carpeta «Soportes».",
        ]
    )
    if mapeo is None:
        doc.parrafo("(No se encontró el mapeo del caso: falta la vista del formulario.)", gris=True)
    return doc.en_bytes()


def _fila_soporte(soporte: EvaluacionSoporte) -> list[Celda]:
    texto, color = ESTADO_SOPORTE[soporte.estado]
    return [
        NOMBRES_SOPORTE[soporte.tipo],
        (texto, color),
        vence(soporte),
        QUE_HACER[soporte.estado],
    ]


# ---------- 2. Formulario (vista de la demo) ----------


def _formulario(mapeo: Mapeo, cliente: str, formato_nombre: str | None) -> bytes:
    doc = DocumentoPdf(f"Formulario de registro · {cliente}", "Vista de la demostración")
    if formato_nombre:
        doc.parrafo(f"Formulario del cliente: {formato_nombre}")
    doc.parrafo(
        "Estos son los valores que el agente llenó en el formulario. La cuenta bancaria y "
        "la identificación del representante aparecen enmascaradas porque esta es una "
        "demostración pública; en el sistema, el formulario real lleva los valores completos."
    )
    # El estado de cada campo (como lo dice `valores_para_copiar`), en palabras y color.
    estados: dict[str, tuple[str, Color | None]] = {
        "listo": ("Listo", None),
        "FALTA en el maestro": ("Falta en el maestro", AMARILLO),
        "PENDIENTE de confirmación": ("Por confirmar", NARANJA),
    }
    filas: list[list[Celda]] = []
    for v in valores_para_copiar(mapeo):
        valor = f"{v.valor} (enmascarado)" if v.enmascarado else (v.valor or "")
        filas.append([v.etiqueta, valor, estados.get(v.estado, (v.estado, None))])
    doc.tabla(["Campo", "Valor", "Estado"], filas, anchos=(38, 47, 25))
    doc.parrafo(
        "Amarillo: el dato no está en el maestro de la empresa (no se inventa). "
        "Naranja: el valor necesita la confirmación de la analista antes de usarse.",
        tamano=8,
        gris=True,
    )
    return doc.en_bytes()


# ---------- 3 y 4. Borrador y constancia (vienen en Markdown) ----------


def _desde_md(
    titulo: str, manifiesto: Manifiesto, archivo: Path, *, es_borrador: bool = False
) -> bytes:
    doc = DocumentoPdf(f"{titulo} · {manifiesto.cliente}", f"Caso {manifiesto.caso}")
    texto = archivo.read_text(encoding="utf-8")
    if es_borrador:
        # El aviso del borrador dice "resuelva lo pendiente en `checklist.md`": en la
        # descarga, ese archivo es el "1. Resumen del caso". (En la constancia NO se
        # cambia: su tabla lista los archivos del sistema con su nombre real.)
        texto = texto.replace("`checklist.md`", f"«{RESUMEN.removesuffix('.pdf')}»")
    desde_markdown(doc, texto)
    return doc.en_bytes()


# ---------- 5. Trazabilidad ----------


def _trazabilidad(manifiesto: Manifiesto) -> bytes:
    doc = DocumentoPdf(
        f"De dónde salió cada dato · {manifiesto.cliente}",
        f"Caso {manifiesto.caso} · paquete armado el {manifiesto.fecha_ejecucion.isoformat()} "
        f"· versión del maestro: {manifiesto.version_maestro}",
    )
    doc.parrafo(
        "El agente nunca inventa un valor: cada campo lleno sale del repositorio maestro de "
        "la empresa. Si un dato no está, el campo queda vacío y se marca como faltante. Si el "
        "valor no es seguro, queda por confirmar hasta que la analista decida."
    )
    filas: list[list[Celda]] = []
    for campo in manifiesto.campos:
        texto, color = ESTADO_CAMPO[campo.estado]
        filas.append(
            [
                campo.etiqueta,
                (texto, color),
                _dato_del_maestro(campo.ruta),
                COMO_SE_ENCONTRO[campo.metodo],
                _decision(campo.decision, campo.confirmado_por, campo.confirmado_en),
            ]
        )
    doc.tabla(
        ["Campo", "Estado", "Dato del maestro", "Cómo se encontró", "Decisión de la analista"],
        filas,
        anchos=(30, 20, 25, 30, 25),
    )
    doc.seccion("Control de los archivos")
    doc.parrafo(
        "Cada archivo del paquete tiene una huella digital (SHA-256) guardada en el sistema: "
        "si alguien cambia un solo carácter, la huella deja de coincidir."
    )
    doc.tabla(
        ["Archivo del sistema", "Tamaño", "Huella (primeros caracteres)"],
        [[a.nombre, f"{a.bytes} bytes", a.sha256[:16]] for a in manifiesto.archivos],
        anchos=(50, 20, 40),
    )
    return doc.en_bytes()


def _dato_del_maestro(ruta: str | None) -> str:
    """ "banco.numero_cuenta" → "banco > numero cuenta" (más fácil de leer)."""
    return ruta.replace(".", " > ").replace("_", " ") if ruta else "-"


def _decision(decision: str | None, por: str | None, en: datetime | None) -> str:
    if decision is None:
        return "-"
    que = "Aceptó el valor" if decision == "aceptar" else "Lo dejó vacío"
    cuando = f" el {en:%Y-%m-%d}" if en else ""
    return f"{que} ({por or 'analista'}{cuando})"


# ---------- Soportes ----------


def _soporte(soporte: EvaluacionSoporte, archivo: Path) -> bytes:
    """Un soporte como PDF. Si el original ya es PDF (en producción), va tal cual."""
    if archivo.suffix.lower() == ".pdf":
        return archivo.read_bytes()
    nombre = NOMBRES_SOPORTE[soporte.tipo]
    texto, color = ESTADO_SOPORTE[soporte.estado]
    doc = DocumentoPdf(nombre, "Documento de ejemplo (empresa ficticia)")
    doc.recuadro(f"Estado: {texto} · vence: {vence(soporte)}", color)
    doc.parrafo(soporte.nota[:1].upper() + soporte.nota[1:])
    filas = _datos_del_soporte(archivo.read_text(encoding="utf-8"))
    if filas:
        doc.seccion("Datos del documento")
        doc.tabla(["Dato", "Valor"], filas, anchos=(35, 75))
    doc.parrafo(
        "En la demostración los soportes son documentos de ejemplo. En producción, aquí va "
        "el documento real (por ejemplo, el PDF del certificado), tal como está en el "
        "repositorio de la empresa.",
        tamano=8,
        gris=True,
    )
    return doc.en_bytes()


def _datos_del_soporte(texto: str) -> list[list[Celda]]:
    """Las líneas "Dato: valor" del soporte de ejemplo, sin las que son técnicas.

    El soporte de ejemplo trae una marca ("PLACEHOLDER…") y el código del tipo, que no le
    dicen nada a una persona; el emisor viene como código de país ("CO" → "Colombia").
    """
    filas: list[list[Celda]] = []
    for linea in texto.splitlines():
        clave, separador, valor = linea.partition(":")
        if not separador or clave.strip().lower() == "tipo":
            continue
        valor = valor.strip()
        if clave.strip().lower() == "emisor":
            valor = next((n for pais, n in NOMBRES_PAIS.items() if pais == valor), valor)
        filas.append([clave.strip(), valor])
    return filas
