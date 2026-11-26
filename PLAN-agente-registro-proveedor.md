# Agente conversacional "Registro como Proveedor"

> Planteamiento del problema y planeación del proyecto
> Versión 1.0 · Estado: **planeación** (todavía sin implementación)

---

## 0. Ficha del proyecto

| Elemento | Definición |
|---|---|
| **Qué es** | Un agente conversacional que prepara los formularios de registro como proveedor que piden los clientes. Llena los campos desde un repositorio maestro, genera el formulario en el formato del cliente y arma el paquete de soportes para la firma. |
| **Qué no es** | No firma, no envía y no carga nada en portales por su cuenta. Todo lo que sale de la empresa lo decide una persona. |
| **Usuaria principal** | Analista administrativa. |
| **Lenguaje** | Python 3.12+. |
| **Modelo de lenguaje** | **Anthropic (Claude)**. Por defecto un modelo económico (`claude-haiku-5-5`), configurable. Se accede detrás de un adaptador propio, para poder cambiar de proveedor sin tocar el agente. La clave vive solo en variables de entorno o en un gestor de secretos. |
| **Etapa actual** | Planeación. Este documento define el problema, el alcance, la arquitectura y el plan de trabajo. |

---

## 1. Resumen ejecutivo

### Contexto de la empresa

La empresa presta **servicios a otras empresas** (sus clientes) en varios países de Latinoamérica: Colombia, Ecuador, Perú, Panamá y Honduras.

Antes de que un cliente pueda contratarla, emitirle una orden de compra y pagarle sus facturas, el cliente exige que la empresa quede **inscrita como proveedor** en su propio sistema. Es un trámite estándar en las empresas medianas y grandes. Así el cliente verifica que:

- la empresa **existe legalmente** (Cámara de Comercio o su equivalente),
- está **al día con sus obligaciones** tributarias y laborales (RUT, parafiscales),
- es **financieramente sólida** (estados financieros),
- tiene una **cuenta bancaria propia** a la que se le puede pagar (certificación bancaria).

Cada cliente tiene **su propio formato**: una plantilla Excel, un formulario PDF o un portal web. También pide **sus propios soportes**. Aun así, los datos que se entregan son casi siempre los mismos: los de la empresa. Sin este registro, **no se puede facturar ni cobrar**, así que cualquier demora retrasa directamente el ingreso de dinero.

### El problema y la propuesta

El área administrativa de la empresa pierde capacidad y necesita automatizar el trabajo repetitivo. El proceso con mayor retorno inmediato es el **registro como proveedor ante clientes**. Llegan entre 8 y 12 solicitudes al mes, y la información que piden ya existe en un repositorio interno. Hoy se transcribe a mano en Excel, en PDF o en portales web.

El proyecto construye un agente que, a partir de una solicitud recibida por correo:

1. identifica los campos y los soportes que pide el cliente,
2. llena cada campo desde el repositorio maestro, con trazabilidad del origen de cada dato,
3. genera el formulario en el formato solicitado,
4. arma un paquete listo para la firma del representante legal, con un checklist y un borrador de correo.

El agente **prepara**. Una persona **revisa, firma y envía**.

---

## 2. Planteamiento del problema

### 2.1 Situación actual (as-is)

| Dimensión | Hoy |
|---|---|
| Volumen | 8–12 solicitudes al mes. |
| Origen | Correos de clientes en Colombia, Ecuador, Perú, Panamá y Honduras. Llegan a recepción. |
| Datos | Casi siempre son los mismos. Están en un repositorio interno junto con los soportes: Cámara de Comercio, RUT, certificación bancaria, parafiscales y estados financieros. |
| Variabilidad | Está en el **formato de salida**: una plantilla Excel del cliente, un formulario PDF o un portal web con usuario y contraseña. También cambian los nombres de los campos (por ejemplo, "Razón social", "Nombre de la empresa" o "Nombre o razón social del proveedor"). |
| Cierre | Firma del representante legal, física o electrónica. |
| Esfuerzo | Transcribir campo por campo, buscar los soportes, revisar su vigencia y redactar el correo de respuesta. |

### 2.2 Dolores

1. **Retrabajo y errores**: la misma información se transcribe cada vez. Hay riesgo de equivocarse en datos sensibles como la cuenta bancaria o el NIT.
2. **Dependencia de una persona**: no está sistematizado dónde está cada soporte, qué pide cada país ni cuándo vence cada documento.
3. **Tiempo de respuesta**: un registro puede tardar días en cola, y eso retrasa la facturación al cliente.
4. **Soportes vencidos**: se detectan tarde, a veces cuando el cliente ya rechazó el paquete.

### 2.3 Por qué un agente y no solo un script

Llenar los campos y revisar los soportes es trabajo **determinista**: es mejor resolverlo con código. El agente conversacional aporta lo que el código solo no resuelve bien:

- una interfaz en lenguaje natural para la analista ("procesa la solicitud X", "¿qué me falta?", "¿por qué ese campo quedó en confirmación?"),
- la orquestación de los pasos y una explicación clara del resultado,
- sugerencias para etiquetas nuevas que no están en el glosario. Son solo sugerencias: nunca se llenan solas.

**Principio rector:** *la lógica de negocio vive en las herramientas, no en el modelo*. El modelo decide qué herramienta llamar y conversa. Los valores, las validaciones y las reglas salen siempre de código determinista y probado.

---

## 3. Objetivos, métricas y no-objetivos

### 3.1 Objetivos

| # | Objetivo | Métrica de éxito |
|---|---|---|
| O1 | Eliminar la transcripción manual en Excel y PDF. | 100 % de los campos que existen en el maestro se llenan sin intervención humana en los casos de referencia. |
| O2 | Hacer explícito lo que falta. | 0 valores inventados. Todo campo sin fuente aparece en el reporte de faltantes. |
| O3 | Preparar el cierre humano. | Cada caso termina con un paquete y una pregunta de confirmación. 0 acciones externas sin confirmación. |
| O4 | Reducir el tiempo de respuesta. | Pasar de días a menos de 15 minutos de trabajo de la analista por solicitud. |
| O5 | Detectar a tiempo los soportes vencidos. | 100 % de los soportes vencidos o próximos a vencer (≤ 15 días) quedan señalados en el checklist. |

### 3.2 No-objetivos (por ahora)

- Integración real con el correo, SharePoint, la firma electrónica o los portales de los clientes. Quedan para fases posteriores.
- Autenticación, roles o multiusuario. La demo es **abierta, sin clave**, para mostrarla a muchas personas (decisión del Paso 18): el gasto y el uso se controlan con topes y con un alcance restringido (ver sección 13).
- Base de datos. En el MVP alcanza con el sistema de archivos.

---

## 4. Actores

| Actor | Rol | Interacción con el agente |
|---|---|---|
| **Recepción** | Recibe el correo del cliente. | Deja la solicitud en la carpeta de entrada. No usa el agente. |
| **Analista administrativa** (usuaria principal) | Prepara el formulario y los soportes. | Conversa con el agente, revisa los faltantes y aprueba el paquete. |
| **Representante legal** | Firma el formulario. | Recibe el paquete listo. No interactúa con el agente. |
| **Dueño del dato maestro** | Mantiene actualizados el maestro y los soportes. | Recibe las alertas de vencimiento y de datos faltantes. *(Rol nuevo que propone este proyecto.)* |
| **Cliente** | Solicita el registro. | Está fuera del sistema. |

---

## 5. Alcance por fases

| Fase | Alcance | Resultado |
|---|---|---|
| **F0 · Fundaciones** | Estructura del repositorio, modelos de datos con Pydantic, carga y validación de los fixtures, pruebas base, CI. | Los datos de entrada se validan y se reportan los errores. |
| **F1 · Núcleo determinista** | Lectura de la solicitud, mapeo de campos, reglas de país, generación de Excel y PDF, paquete y checklist. Script `demo.py` sin modelo. | Los 4 casos de referencia se procesan sin LLM, siempre con el mismo resultado. |
| **F2 · Agente y chat** | Adaptador de LLM, ciclo del agente, API, front de chat con las llamadas a herramientas visibles y la confirmación humana. | La analista procesa un caso conversando. |
| **F3 · Despliegue y operación** | Contenedor, despliegue, logs, límites de costo, evaluaciones del agente. | URL estable y métricas de uso y costo. |
| **F4 · Portal asistido** *(posterior)* | Valores listos para copiar y, después, un navegador asistido donde la persona ingresa las credenciales y hace clic en "Enviar". | Menos tiempo en los portales, con el control humano intacto. |
| **F5 · Integraciones** *(posterior)* | Lectura del correo, repositorio en SharePoint, firma electrónica. | Flujo de punta a punta, siempre con la aprobación humana. |

---

## 6. Historias de usuario y criterios de aceptación

### HU-1 · Leer la solicitud
**Como** analista, **quiero** que el agente lea el correo del cliente y la plantilla adjunta **para** saber qué campos y qué soportes me piden sin abrir cada archivo.

- Dados `solicitud.json` y su plantilla (`plantilla-celdas.json` para Excel o `plantilla-campos.json` para PDF), el agente devuelve: el país, el cliente, el formato (`xlsx`, `pdf` o `portal`), los campos solicitados y los soportes exigidos.
- Los campos ambiguos (por ejemplo, "Identificación tributaria") se reportan como `requiere_confirmacion`, con el equivalente del país: NIT en Colombia, RUC en Ecuador, Perú y Panamá, y RTN en Honduras.
- Una plantilla con estructura inválida se reporta con un mensaje claro que indica qué parte está mal.
- La analista puede referirse al caso por el cliente o el país ("el de Ecuador"). El agente lista los casos disponibles (`proveedor_listar_casos`) para identificarlo y, si hay más de uno posible, pregunta cuál es.

### HU-2 · Mapear los campos al maestro
**Como** analista, **quiero** que cada campo se cruce con el repositorio maestro **para** que el llenado sea exacto y trazable.

- Cada campo termina en uno de tres estados:
  - `lleno`: incluye la ruta del dato en el maestro y el método de mapeo.
  - `faltante`: el dato no existe en el maestro.
  - `requiere_confirmacion`: la confianza es menor a 0.8 o aplica una regla de país.
- **Nunca** se inventa un valor. Un campo sin fuente queda `faltante`.
- Los sinónimos del glosario se resuelven solos, sin importar mayúsculas, tildes ni espacios.
- *(Buena práctica)* Cada campo guarda **cómo** se mapeó: `glosario_exacto`, `glosario_normalizado`, `similitud` (con su puntaje) o `sugerencia_llm`. Solo los dos primeros pueden quedar `lleno` sin revisión.
- La analista puede **resolver** un campo en `requiere_confirmacion` (`proveedor_confirmar_campo`): aceptar el valor propuesto o dejarlo como `faltante`. La decisión queda registrada en el mapeo del caso, con quién confirmó y cuándo, y el formulario se regenera con ese valor. El agente **no puede confirmar por su cuenta**: la confirmación pasa por una aprobación explícita en el front.

### HU-3 · Generar el formulario en el formato pedido
**Como** analista, **quiero** el formulario lleno en el mismo formato que envió el cliente **para** no reformatear nada.

- **Excel**: `out/<caso>/formulario.xlsx`, con cada etiqueta y su valor exactamente en la hoja y la celda que indica la plantilla.
- **PDF**: `out/<caso>/formulario.pdf`, con todos los campos (etiqueta y valor) en el orden dado. Si el cliente envía un PDF con campos rellenables (AcroForm), se rellena ese mismo archivo.
- **Portal**: no se automatiza en el MVP. El agente responde "formato no soportado" y genera `out/<caso>/valores-portal.md` con los valores listos para copiar.
- Los campos `faltante` quedan vacíos y se resaltan, nunca con un texto de relleno.

### HU-4 · Armar el paquete para firma
**Como** analista, **quiero** un paquete con el formulario, los soportes y un borrador de correo **para** mandarlo a firma en un solo paso.

- Se crea `out/<caso>/paquete/` con el formulario, las copias de los soportes exigidos que existan, `checklist.md` y `borrador-correo.md`.
- El checklist marca cada soporte como **presente**, **ausente**, **vencido** o *(buena práctica)* **por vencer**, comparando `vigencia_hasta` con la fecha de ejecución.
- Un soporte vencido o ausente bloquea el estado `listo_para_firma`.
- El agente cierra con un resumen y una **pregunta explícita** de confirmación.

### HU-5 · Envío con confirmación
**Como** analista, **quiero** que nada salga sin mi aprobación **para** mantener el control.

- La herramienta de envío solo se ejecuta si hay una confirmación pendiente **registrada por el servidor** y el usuario la aprueba en el turno siguiente.
- En el MVP, "enviar" solo escribe `out/<caso>/constancia-envio.md`: una constancia con el destinatario, los archivos y sus huellas y quién aprobó, que dice que en modo piloto la entrega al cliente se hace fuera del sistema. *(Antes se llamaba `ENVIO-SIMULADO.md`; se cambió después del Paso 16, decisión de Anderson.)*

### HU-6 · Manejo de errores
**Como** analista, **quiero** que el agente falle de forma clara **para** no perder tiempo depurando.

- Caso inexistente, plantilla corrupta, formato no soportado o error del proveedor de LLM: se muestra un mensaje claro, sin traza técnica, y el proceso sigue con lo que sí puede hacer.
- Ninguna herramienta lanza una excepción hacia el agente. Todas devuelven `{ok: true, data}` o `{ok: false, error}`.

### HU-7 · Trazabilidad *(buena práctica)*
**Como** responsable del proceso, **quiero** saber qué hizo el agente en cada caso **para** auditarlo.

- Cada llamada a una herramienta queda registrada con la fecha, la sesión, la herramienta, el resultado y un resumen, **sin datos sensibles en claro**.
- Cada paquete incluye un `manifiesto.json` con la versión del maestro, la fecha de ejecución y el origen de cada valor.

---

## 7. Reglas de negocio

| # | Regla |
|---|---|
| RN1 | El identificador tributario se traduce por país: CO → NIT; EC, PE y PA → RUC; HN → RTN. La empresa solo tiene NIT colombiano. Para otros países se llena con el NIT y se marca `requiere_confirmacion` con la nota "identificador extranjero". |
| RN2 | Los datos bancarios se llenan solo si la plantilla los pide explícitamente. **Nunca** van en el borrador de correo. |
| RN3 | Un soporte vencido o ausente bloquea `listo_para_firma`. Un campo `faltante` no lo bloquea, pero aparece en el checklist. |
| RN4 | Ninguna acción externa (envío, firma o carga a un portal) ocurre sin una confirmación explícita del usuario en el turno inmediatamente anterior. |
| RN5 | Toda ejecución deja un registro en `out/<caso>/log.jsonl` con `{ts, herramienta, ok, resumen}`. |
| RN6 *(nueva)* | Un soporte que vence en 15 días o menos se marca "por vencer". No bloquea, pero se avisa. El umbral es configurable. |
| RN7 *(nueva)* | La fecha de ejecución se puede inyectar por parámetro, para que las pruebas y las demostraciones sean reproducibles. |
| RN8 *(nueva)* | Los valores sensibles (cuenta bancaria e identificaciones personales) se enmascaran en los logs y en las respuestas al modelo. Por ejemplo: `****2345`. |

Las reglas viven en archivos de configuración y de conocimiento (`config/reglas.yaml` y `knowledge/`), no en el servidor. Cambiar una regla no debería obligar a tocar el código del API.

---

## 8. Arquitectura propuesta

### 8.1 Vista general

```
┌──────────────┐  HTTP / SSE  ┌──────────────────────────────────────────┐
│  Front chat  │ ───────────▶ │  API (FastAPI)                           │
│  - historial │ ◀─────────── │  - ciclo del agente (con topes)          │
│  - tool calls│              │  - estado de confirmación (servidor)     │
│  - confirmar │              │  - sesiones                              │
└──────────────┘              └──────┬──────────────────────┬────────────┘
                                     │                      │
                          ┌──────────▼─────────┐   ┌────────▼─────────┐
                          │ Herramientas       │   │ Adaptador LLM    │
                          │ (Pydantic, puras)  │   │ (Protocol)       │
                          └──────────┬─────────┘   └──────────────────┘
                                     │
                          ┌──────────▼─────────────────────────────┐
                          │ Núcleo de dominio (sin LLM ni HTTP)     │
                          │ lectura · mapeo · reglas · generadores  │
                          └──────────┬─────────────────────────────┘
                                     │
                    datos/ (solo lectura)          out/ (escritura)
```

**Capas:**

1. **Dominio** (`dominio/`): modelos, mapeo, reglas y generadores de Excel y PDF. No sabe nada de LLM ni de HTTP. Es lo que más se prueba.
2. **Herramientas** (`herramientas/`): envuelven el dominio con un contrato estable (entrada validada → `Resultado`). Las usan tanto el agente como `demo.py`.
3. **Agente** (`agente/`): el ciclo, el prompt, el adaptador de LLM y los guardarraíles.
4. **API y front** (`api/`, `web/`): solo transporte y presentación.

### 8.2 Stack técnico

| Necesidad | Elección | Alternativa descartada y por qué |
|---|---|---|
| Gestión de proyecto y dependencias | **uv** + `pyproject.toml` | pip + requirements.txt: sin lockfile reproducible y más lento. |
| API | **FastAPI** + Uvicorn | Flask: no tiene validación ni documentación OpenAPI integradas. |
| Validación y esquemas de herramientas | **Pydantic v2** (genera el JSON Schema que ve el modelo) | Esquemas escritos a mano: se desincronizan con el código. |
| Configuración y secretos | **pydantic-settings** (`.env` en local, gestor de secretos en producción) | `os.environ` suelto: sin validación ni tipos. |
| Excel | **openpyxl** | pandas: es demasiado para escribir celdas puntuales y pierde el formato. |
| PDF generado | **fpdf2** (o ReportLab) | WeasyPrint: depende de librerías del sistema y complica el despliegue. |
| PDF rellenable (AcroForm) | **pypdf** | — |
| Similitud de etiquetas | **rapidfuzz** | difflib: más lento y menos preciso. |
| Plantillas de checklist y correo | **Jinja2** | f-strings: mezclan texto de negocio con código. |
| SDK del LLM | **SDK oficial de Anthropic** (`anthropic`), detrás de un `Protocol` | Frameworks pesados de agentes: más magia, menos control del ciclo y de los costos. |
| Front | HTML + JS simple (o HTMX) servido por FastAPI | Streamlit: rápido de prototipar, pero da poco control para mostrar las llamadas a herramientas y la confirmación. Sirve como alternativa para un prototipo interno. |
| Calidad | **ruff** (lint y formato), **mypy** o **pyright** (tipos estrictos), **pytest** | — |
| Logs | **structlog** en JSON | `print`: no se puede consultar ni auditar. |
| Despliegue | **Docker** + un servicio administrado (Render, Railway, Azure App Service o Cloud Run) | Servidor propio: más operación para un volumen bajo. |

### 8.3 Estructura del repositorio

```
registro-proveedor/
├── pyproject.toml
├── uv.lock
├── .env.example
├── Dockerfile
├── README.md
├── docs/
│   ├── PLAN.md                    # este documento
│   └── decisiones/                # ADRs: una decisión por archivo
├── config/
│   └── reglas.yaml                # umbrales, mapeo país → identificador, días "por vencer"
├── knowledge/
│   └── registro-proveedor.md      # conocimiento del proceso que consulta el agente
├── agente/
│   └── prompt.md                  # system prompt (comportamiento)
├── src/registro_proveedor/
│   ├── config.py                  # settings con pydantic-settings
│   ├── dominio/
│   │   ├── modelos.py             # Solicitud, Plantilla, Maestro, Soporte, CampoMapeado…
│   │   ├── lectura.py             # carga y valida casos
│   │   ├── mapeo.py               # glosario → normalizado → similitud
│   │   ├── reglas.py              # país, banca, vigencias
│   │   ├── generadores/
│   │   │   ├── excel.py
│   │   │   ├── pdf.py
│   │   │   └── portal.py          # valores-portal.md
│   │   └── paquete.py             # checklist, borrador, manifiesto
│   ├── herramientas/
│   │   ├── base.py                # Resultado, decorador @herramienta, registro
│   │   └── proveedor.py           # leer_solicitud, mapear_campos, …
│   ├── agente/
│   │   ├── ciclo.py               # bucle con topes
│   │   ├── confirmacion.py        # estado de confirmación del servidor
│   │   ├── guardarrailes.py       # verificación de valores en la respuesta
│   │   └── llm/
│   │       ├── adaptador.py       # Protocol: enviar(mensajes, herramientas) → Respuesta
│   │       └── <proveedor>.py
│   ├── api/
│   │   └── app.py                 # FastAPI: /api/chat, /api/sessions/{id}, /api/health
│   └── observabilidad.py          # logs y enmascaramiento
├── web/                           # front de chat
├── datos/                         # solicitudes, maestro y soportes (solo lectura)
├── out/                           # generado al ejecutar (en .gitignore)
├── scripts/
│   └── demo.py                    # todos los casos sin LLM
└── tests/
    ├── unit/                      # reglas, mapeo, generadores
    ├── golden/                    # salida esperada por caso
    └── evals/                     # conversaciones guionadas con el agente
```

**Separación clave:** el **comportamiento** está en `agente/prompt.md`, el **conocimiento** en `knowledge/` y `config/`, y la **ejecución** en `herramientas/` y `dominio/`.

---

## 9. Diseño del agente

### 9.1 Contrato de herramientas

Cada herramienta tiene un modelo de entrada en Pydantic, una descripción de una frase y devuelve un `Resultado`. **Nunca lanza excepciones.**

```python
# src/registro_proveedor/herramientas/base.py
from typing import Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")

class Resultado(BaseModel, Generic[T]):
    ok: bool
    data: T | None = None
    error: str | None = None   # mensaje claro para el usuario, sin traza

# src/registro_proveedor/herramientas/proveedor.py
class LeerSolicitudArgs(BaseModel):
    caso: str = Field(pattern=r"^[a-z0-9-]+$",
                      description="Carpeta del caso dentro de datos/casos/")

@herramienta(nombre="proveedor_leer_solicitud",
             descripcion="Lee la solicitud y la plantilla de un caso y devuelve país, formato, campos y soportes.")
def leer_solicitud(args: LeerSolicitudArgs, ctx: Contexto) -> Resultado[SolicitudLeida]:
    ...
```

- El decorador `@herramienta` registra la función, genera el JSON Schema desde Pydantic, valida los argumentos antes de ejecutar y captura cualquier excepción para convertirla en `Resultado(ok=False, error=...)`.
- `ctx` trae la raíz del proyecto, la sesión, la fecha de ejecución y el logger. Las rutas se resuelven desde ahí y se valida que no salgan de `datos/` ni de `out/` (protección contra *path traversal*).

| Herramienta | Entrada | Salida (`data`) |
|---|---|---|
| `proveedor_listar_casos` | `filtro?` (cliente o país, opcional) | `casos[]` con `caso`, `cliente`, `pais`, `formato`, `fecha` |
| `proveedor_leer_solicitud` | `caso` | `pais`, `cliente`, `formato`, `campos[]`, `soportes[]` |
| `proveedor_mapear_campos` | `caso` | `llenos[]`, `faltantes[]`, `requiere_confirmacion[]` (con origen y método); el mapeo se guarda en `out/<caso>/mapeo.json` |
| `proveedor_confirmar_campo` ⚠ | `caso`, `etiqueta`, `decision` (`aceptar` \| `dejar_faltante`) | campo actualizado y resumen del mapeo; **requiere aprobación humana** |
| `proveedor_generar_formulario` | `caso` | `ruta`, `formato` |
| `proveedor_armar_paquete` | `caso` | `ruta`, `listo_para_firma`, `checklist` |
| `proveedor_registrar_envio` ⚠ | `caso` | `ruta` de la constancia de envío, o un error si no hay confirmación válida; **requiere aprobación humana** *(se llamaba `proveedor_simular_envio`; se renombró en el Paso 16 para la demo, decisión de Anderson)* |

⚠ = la herramienta está marcada `requiere_confirmacion=True`: el servidor no la ejecuta al pedirla, sino que crea una confirmación pendiente que la persona aprueba o rechaza en el front.

*(Buena práctica)* `generar_formulario` **no recibe el mapeo desde el modelo**: lo recalcula o lo lee del estado de la sesión. Así el modelo no puede alterar los valores entre un paso y otro.

### 9.2 Mapeo de campos en capas

| Paso | Método | Confianza | Estado posible |
|---|---|---|---|
| 1 | Coincidencia exacta en el glosario | 1.0 | `lleno` |
| 2 | Coincidencia en el glosario tras normalizar (minúsculas, sin tildes ni signos) | 0.95 | `lleno` |
| 3 | Similitud con rapidfuzz contra las etiquetas del glosario | puntaje / 100 | `lleno` si ≥ 0.9; `requiere_confirmacion` si está entre 0.8 y 0.9 |
| 4 | Sugerencia del LLM para etiquetas nuevas | — | Siempre `requiere_confirmacion` |
| — | Sin fuente en el maestro | — | `faltante` |

Las reglas de país (RN1) se aplican **después** del mapeo y pueden bajar un campo `lleno` a `requiere_confirmacion`.

Esos campos se resuelven con `proveedor_confirmar_campo`, siempre con aprobación humana.

Cuando la analista confirma un mapeo nuevo, se propone agregarlo al glosario. **El glosario mejora con el uso**, pero siempre con una aprobación humana.

### 9.3 Ciclo del agente

```
mensaje usuario  ·  botón Aprobar / Rechazar
   │
   ▼
[¿hay confirmación pendiente?] ── sí ──▶ ¿pulsó Aprobar? ── sí ──▶ ejecutar la acción guardada (argumentos fijos)
   │ no                                         │ no (Rechazar, o escribió otro mensaje)
   ▼                                            ▼
LLM (prompt + historial + herramientas)     cancelar la pendiente
   │
   ├── texto ──────────────▶ guardarraíl de valores ──▶ respuesta al usuario
   │
   └── tool_use ──▶ validar argumentos ──▶ ejecutar ──▶ tool_result ──▶ (vuelve al LLM)
                  (tope: N iteraciones, M tokens por sesión, timeout por llamada)
```

| # | Regla del ciclo |
|---|---|
| CA1 | Tope de iteraciones por turno (por defecto 15) y tope de tokens por sesión, ambos configurables. Si se alcanza, el agente responde con lo que tiene y lo que falta. |
| CA2 | El modelo no puede afirmar valores que no hayan salido de una herramienta. Lo prohíbe el prompt y lo verifica un guardarraíl (9.4). |
| CA3 | **La confirmación humana la controla el servidor, no el prompt.** Una herramienta marcada `requiere_confirmacion=True` crea una confirmación pendiente en lugar de ejecutarse. El front muestra los botones Aprobar y Rechazar. Solo una aprobación explícita del usuario la ejecuta: un texto como "sí" no aprueba *(aclarado en el Paso 13)*. |
| CA4 | Toda llamada a una herramienta queda visible en el chat y en `out/log.jsonl`. |
| CA5 | Los errores de una herramienta o del LLM se muestran en lenguaje claro y la sesión sigue viva. Hay reintentos con *backoff* exponencial para los errores transitorios del proveedor (429 y 5xx). |
| CA6 *(nueva, ajustada en el Paso 10)* | Sin `temperature`: `claude-haiku-5-5` y la versión actual de la API la rechazan. La consistencia la dan el núcleo determinista (los valores, las reglas y los formularios no dependen del modelo) y el **esfuerzo** (`effort`), `medium` por defecto y configurable con `LLM_ESFUERZO`; en el Paso 17 se mide si `low` alcanza. |
| CA7 *(nueva)* | Caché de prompts del proveedor para el system prompt y las definiciones de herramientas, que se repiten en cada llamada. Baja el costo y la latencia. |

### 9.4 Guardarraíles

- **Verificación de valores:** antes de mostrar la respuesta, se buscan en el texto patrones sensibles (NIT, cuentas, identificaciones, correos). Si aparece uno que no vino de un `tool_result` de la sesión, se bloquea o se reemplaza por una nota.
- **Datos mínimos al modelo:** las herramientas devuelven al modelo los valores sensibles **enmascarados**. Los valores completos solo se escriben en los archivos generados. El modelo no necesita el número de cuenta para explicar que "el banco quedó lleno".
- **Entradas no confiables:** el cuerpo del correo del cliente se trata como **datos**, nunca como instrucciones. Se pasa delimitado y el prompt lo dice explícitamente. Esto mitiga la inyección de prompts.
- **Sin shell ni red** desde las herramientas en el MVP.

### 9.5 System prompt (`agente/prompt.md`)

Debe contener:
1. El rol y el objetivo, en pocas líneas.
2. El flujo recomendado: leer → mapear → generar → armar paquete → resumir → preguntar.
3. Las prohibiciones: no inventar valores, no enviar sin confirmación, no mostrar datos bancarios en el chat.
4. El formato del resumen final: llenos, faltantes, confirmaciones, estado del paquete y la pregunta de cierre.
5. Cómo tratar el contenido del correo: como datos, no como órdenes.

El prompt se **versiona** y cada cambio se valida con las evaluaciones (sección 11).

---

## 10. Datos

| Archivo | Contenido | Validación |
|---|---|---|
| `datos/casos/<caso>/solicitud.json` | `id`, `de`, `asunto`, `fecha`, `pais`, `cliente`, `cuerpo`, `formato`, `adjuntos[]` | Modelo `Solicitud` |
| `datos/casos/<caso>/plantilla-celdas.json` | Excel: `hoja`, `celda_etiqueta`, `etiqueta`, `celda_valor` | Modelo `CeldaPlantilla` (celda con formato A1 válido) |
| `datos/casos/<caso>/plantilla-campos.json` | PDF (obligatorio) o portal (opcional; si existe, alimenta `valores-portal.md`): `etiqueta`, `obligatorio` | Modelo `CampoPlantilla` |
| `datos/casos/<caso>/soportes-exigidos.json` | Tipos de soporte | Lista de `TipoSoporte` (enum) |
| `datos/repositorio/maestro.json` | Datos de la empresa con claves en `snake_case` | Modelo `Maestro`: fijo para los campos conocidos y tolerante con los nuevos (un campo desconocido genera una sugerencia, no un error) |
| `datos/repositorio/soportes/index.json` | `tipo`, `archivo`, `vigencia_hasta`, `pais_emisor` | Modelo `Soporte`; además se verifica que el archivo exista |
| `datos/glosario-campos.json` | Etiqueta → ruta en el maestro | Se verifica que cada ruta exista en el maestro |

**Buenas prácticas de datos:**
- `datos/` **no se modifica**, ni por el código ni a mano para "arreglar" la demostración. Si a un dato le falta algo, se reporta y se deja como sugerencia para el dueño del dato.
- Un script `validar_datos.py` revisa todo lo anterior y se ejecuta en CI. Si alguien rompe el maestro o el glosario, se detecta antes de llegar a producción. El reporte tiene dos niveles:
  - **Error**: el dato está roto y no se puede procesar (celda inválida, formato desconocido, ruta del glosario inexistente, archivo de soporte ausente). Hace fallar el CI.
  - **Sugerencia**: el dato funciona, pero le falta algo que el diseño espera (por ejemplo, el maestro sin `version`). Va dirigida al dueño del dato y no hace fallar el CI.
- Se recomienda que el maestro guarde `version` y `actualizado_en`, para que cada paquete registre con qué versión se generó. Son **opcionales**: si faltan, `validar_datos.py` lo sugiere y el manifiesto dice "maestro sin versión", sin inventarla. *(Los datos de ejemplo no los tienen.)*
- El maestro tiene un **dueño del dato** con responsabilidad formal.

**Casos de referencia** (para las pruebas y la demostración):

| Caso | País | Formato | Qué pone a prueba |
|---|---|---|---|
| Cliente CO | Colombia | Excel (2 hojas) | Llenado completo, datos bancarios pedidos explícitamente. |
| Cliente EC | Ecuador | PDF | RUC → NIT con confirmación, campo faltante, soporte exigido que no existe. |
| Cliente HN | Honduras | Excel | RTN → NIT con confirmación, campo faltante, soporte vencido. |
| Cliente PA | Panamá | Portal | Formato no soportado → valores para copiar. |

---

## 11. Calidad y pruebas

| Nivel | Qué cubre | Herramienta |
|---|---|---|
| Unitarias | Normalización, mapeo, reglas de país, vigencias, enmascaramiento. | pytest |
| Basadas en propiedades *(opcional)* | El mapeo nunca produce un valor que no esté en el maestro. | hypothesis |
| *Golden* por caso | La salida de cada caso (mapeo, checklist, celdas del Excel, texto del PDF) se compara con un resultado esperado guardado en el repositorio. | pytest + snapshots |
| `demo.py` | Corre todos los casos sin LLM e imprime un resumen. Es determinista con fecha fija. | script |
| Evaluaciones del agente | Conversaciones guionadas. Se verifica que llame a las herramientas correctas, que no invente valores, que pida confirmación y que no envíe sin ella. Incluye un correo con texto malicioso. | pytest + LLM real (en CI nocturno o manual) |
| Contrato del API | Las rutas responden con los esquemas documentados. | pytest + httpx |

**CI (en cada *push*):** ruff → mypy → pruebas unitarias y *golden* → `validar_datos.py` → build de Docker. Las evaluaciones con LLM corren aparte porque cuestan dinero.

**Definición de terminado** para cada historia: código tipado sin `Any`, pruebas en verde, log y errores claros, y documentación actualizada.

---

## 12. API

| Método | Ruta | Cuerpo / respuesta |
|---|---|---|
| `POST` | `/api/chat` | `{session_id, message}` → `{reply, tool_calls[], needs_confirmation, confirmation_id?}` o un *stream* SSE |
| `POST` | `/api/confirmations/{id}` | `{session_id, approve: bool}` → ejecuta o cancela la acción pendiente *(el `session_id` se agregó en el Paso 15: así nadie aprueba la confirmación de otra conversación adivinando su id)* |
| `GET` | `/api/sessions/{id}` | Historial de la sesión |
| `GET` | `/api/cases/{caso}/portal-values?session_id=…` | Valores del portal para copiar; lo sensible va enmascarado (Paso 18) |
| `GET` | `/api/health` | `{ok, provider, model}`, sin exponer claves |

La documentación OpenAPI se genera sola en `/docs` gracias a FastAPI.

---

## 13. Requisitos no funcionales

| Categoría | Requisito |
|---|---|
| Arranque | Un comando levanta el front y el backend en local (`uv run dev` o `docker compose up`) en menos de 2 minutos. |
| Determinismo | `demo.py` produce el mismo resultado en ejecuciones consecutivas (salvo los timestamps) y limpia `out/` al iniciar. |
| Seguridad | La clave del modelo solo vive en el backend (variable de entorno o gestor de secretos). Nunca está en el front, el repositorio, los logs ni las respuestas. **Demo abierta sin clave** (Paso 18): el chat solo atiende el registro como proveedor (prompt + topes del código), y la página nunca muestra datos sensibles completos. Las herramientas no ejecutan comandos de shell. |
| Privacidad | Los datos sensibles se enmascaran en logs y respuestas. Al modelo se envía solo lo necesario. Se revisa la política de retención de datos del proveedor de LLM. |
| Costo | Topes de iteraciones por turno, de tokens y de mensajes por sesión, de conversaciones y mensajes por visitante (IP), y de conversaciones y dólares por día, configurables. Se registra el costo estimado por caso. |
| Robustez | Errores tipados. Timeout al LLM (por ejemplo, 30 s) con mensaje claro. Un caso malo no impide procesar el siguiente. |
| Rendimiento | Procesar un caso de punta a punta en menos de 60 s con el LLM y en menos de 2 s sin él. |
| Legibilidad | Tipado estricto, funciones cortas, nombres en español consistentes con el dominio. |
| Observabilidad | Logs JSON con `session_id` y `trace_id`. Métricas de casos procesados, campos llenos o faltantes, errores, tokens y costo. |

---

## 14. Diseño para portales web (fase posterior)

| Aspecto | Propuesta |
|---|---|
| Estrategia | Primero, **valores para copiar** (MVP). Después, un **navegador asistido** con Playwright en modo visible: el agente llena los campos y la persona observa. |
| Límites | CAPTCHA, MFA y cambios de diseño del portal. Por eso el navegador asistido nunca resuelve CAPTCHAs: la persona lo hace. Los selectores de cada portal se guardan en archivos de configuración versionados y se prueban periódicamente. |
| Credenciales | Nunca en el repositorio, el prompt ni los logs. Las **ingresa la persona** directamente en el navegador, o se usa un gestor de contraseñas corporativo. El agente nunca las ve. |
| Reparto de tareas | El agente navega y llena los campos. La persona ingresa las credenciales, revisa y hace clic en **"Enviar"**. |
| Evidencia | Una captura de pantalla antes de enviar se adjunta al manifiesto del paquete. |

---

## 15. Decisiones técnicas (resumen de ADRs)

| # | Decisión | Alternativa descartada | Por qué |
|---|---|---|---|
| D1 | El núcleo es determinista y el LLM solo orquesta. | Que el LLM haga el mapeo directamente. | Exactitud, pruebas reproducibles y cero valores inventados. |
| D2 | La confirmación la controla el servidor. | Confiar en que el prompt "pida permiso". | Un prompt se puede saltar; una regla en el código, no. |
| D3 | Un adaptador propio de LLM en lugar de un framework de agentes. | LangChain o similares. | El ciclo es simple, y así hay control total de topes, costos y errores, y menos dependencias. |
| D4 | Sistema de archivos en el MVP. | Base de datos desde el inicio. | El volumen es bajo (12 casos al mes). Se migra cuando haya multiusuario. |
| D5 | Valores sensibles enmascarados hacia el modelo. | Enviar el maestro completo. | Minimización de datos y menos riesgo si algún log o respuesta se filtra. |
| D6 | Un PDF generado con fpdf2 y AcroForm con pypdf cuando el cliente lo provee. | Solo PDF generado. | Respetar el formato del cliente siempre que se pueda. |

---

## 16. Plan de trabajo

Estimado para una persona. Se ajusta tras la fase F0.

| Semana | Fase | Entregables | Criterio de salida |
|---|---|---|---|
| 1 | F0 | Repositorio con uv, ruff, mypy, pytest y CI. Modelos Pydantic. `validar_datos.py`. | CI en verde y los datos de referencia validados. |
| 2 | F1 | Lectura, mapeo en capas, reglas de país y vigencias, con pruebas unitarias. | 100 % de las reglas con pruebas. |
| 3 | F1 | Generadores de Excel, PDF y portal, paquete, checklist, manifiesto y `demo.py`. Pruebas *golden*. | Los 4 casos se procesan sin LLM y siempre igual. |
| 4 | F2 | Adaptador de LLM, ciclo con topes, confirmación del servidor, guardarraíles, prompt. | Evaluaciones básicas en verde. |
| 5 | F2 | API FastAPI y front de chat con las herramientas visibles y los botones de confirmación. | Demo conversacional completa en local. |
| 6 | F3 | Docker, despliegue, demo abierta con topes, logs y métricas de costo. Documentación y piloto con la analista. | URL estable, piloto con casos reales y retroalimentación recogida. |

**Hitos:** M1 núcleo determinista (fin de la semana 3) · M2 agente en local (fin de la semana 5) · M3 piloto (fin de la semana 6).

---

## 17. Riesgos, supuestos y preguntas abiertas

### 17.1 Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| El modelo "completa" un campo con un valor plausible. | Alto | Los valores solo salen de las herramientas, hay un guardarraíl sobre la respuesta y evaluaciones específicas. |
| Inyección de prompts en el correo del cliente. | Alto | El correo se trata como datos delimitados, no hay acciones externas sin confirmación y se prueba con correos maliciosos. |
| Fuga de datos sensibles (cuenta, identificaciones). | Alto | Enmascaramiento, datos mínimos al modelo, logs sin datos en claro y una página pública que nunca muestra datos sensibles completos. |
| El maestro está desactualizado. | Medio | Dueño del dato, versión en el manifiesto y alertas de vigencia. |
| Plantillas reales peores que las de referencia. | Medio | Mapeo con niveles de confianza, aprendizaje del glosario con aprobación y piloto temprano. |
| Portales con CAPTCHA o MFA. | Medio | La persona opera esas partes y el agente prepara los valores. |
| Costo del LLM sin control. | Bajo | Topes por turno, por sesión, por visitante y por día (también en dólares), caché de prompts y modelo económico. |
| Que usen el chat abierto para otra cosa. | Medio | El prompt responde una frase fija fuera de tema; el código limita mensajes, largo de respuesta y gasto; evaluaciones E8 y E9. |
| Cambio de proveedor de LLM. | Bajo | Adaptador propio y evaluaciones para comparar proveedores. |

### 17.2 Supuestos

- Los casos de referencia representan la variabilidad principal. En producción aparecerán plantillas peores.
- La empresa solo tiene identificador tributario colombiano (NIT).
- El volumen se mantiene en el orden de decenas de solicitudes al mes.

### 17.3 Preguntas abiertas

1. ¿Quién será formalmente el dueño del dato maestro y de los soportes?
2. ¿Qué proveedor de LLM aprueba el área de seguridad, y con qué política de retención de datos?
3. ¿Dónde vivirá el repositorio de soportes en producción (SharePoint, Drive, un servidor de archivos)?
4. ¿La firma electrónica se integrará en una fase posterior? ¿Con qué proveedor?
5. ¿Qué umbral de días "por vencer" prefiere el área administrativa?
6. ¿Los clientes envían PDF rellenables (AcroForm) o solo documentos planos?

---

## 18. Ejemplo de uso esperado

En el chat, con una sesión nueva:

```
Procesa la solicitud del cliente de Ecuador. Dime qué campos quedaron llenos,
cuáles faltan, si el paquete está listo para firma y qué soportes debo
actualizar. No envíes nada todavía.
```

**Resultado esperado:** un resumen estructurado, las llamadas a herramientas visibles, la ruta de `out/<caso>/`, la lista de faltantes y de campos por confirmar, el estado `listo_para_firma` con el motivo si está bloqueado, y una pregunta de cierre con los botones Aprobar y Rechazar.

Si el usuario aprueba el envío, el sistema solo genera la constancia `constancia-envio.md` (modo piloto).
