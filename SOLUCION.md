# Solución — Agente "Registro como Proveedor"

> Documento vivo de construcción. Se llena a medida que avanza el desarrollo.
> Referencia: `PLAN-agente-registro-proveedor.md` (planteamiento y planeación).

**Cómo usar este documento**

- Cada paso tiene un **objetivo**, un criterio de **hecho cuando** y un espacio de **avance** que se completa al terminarlo.
- Estados: ⬜ Pendiente · 🟨 En progreso · ✅ Hecho · ⛔ Bloqueado.
- Los pasos están en el orden en que deben construirse: cada uno se apoya en los anteriores.

---

## Tablero de avance

| # | Paso | Fase | Estado |
|---|---|---|---|
| 1 | Preparación del entorno | F0 | ✅ |
| 2 | Modelos de datos y validación de insumos | F0 | ✅ |
| 3 | Base de herramientas y observabilidad | F0 | ✅ |
| 4 | Listado y lectura de solicitudes | F1 | ✅ |
| 5 | Mapeo de campos y su confirmación | F1 | ✅ |
| 6 | Reglas de negocio configurables | F1 | ✅ |
| 7 | Generación de formularios | F1 | ✅ |
| 8 | Paquete para firma | F1 | ✅ |
| 9 | Demostración sin modelo y pruebas *golden* | F1 | ✅ |
| 10 | Adaptador del modelo de lenguaje | F2 | ✅ |
| 11 | System prompt y base de conocimiento | F2 | ⬜ |
| 12 | Ciclo del agente | F2 | ⬜ |
| 13 | Confirmación humana y envío simulado | F2 | ⬜ |
| 14 | Guardarraíles | F2 | ⬜ |
| 15 | API | F2 | ⬜ |
| 16 | Front de chat | F2 | ⬜ |
| 17 | Evaluaciones del agente | F3 | ⬜ |
| 18 | Seguridad y control de costos | F3 | ⬜ |
| 19 | Contenedor y despliegue | F3 | ⬜ |
| 20 | Módulo reutilizable | F3 | ⬜ |
| 21 | Piloto con la usuaria | F3 | ⬜ |

---

# Parte A · Pasos de construcción

## Fase F0 · Fundaciones

### Paso 1 · Preparación del entorno
**Objetivo:** tener un repositorio que se instale y se pruebe con un solo comando, con calidad automática desde el primer día.
**Hecho cuando:** `uv sync` instala todo, `uv run pytest` corre, el CI (ruff + mypy + pytest) está en verde y `.env.example` lista las variables sin valores.
**Estado:** ✅
**Avance:**
- **Instalación en un comando.** `pyproject.toml` lista las librerías y `uv.lock` guarda sus versiones exactas. Con `uv sync`, cualquier persona instala exactamente lo mismo.
- **Configuración en un solo lugar.** `config.py` lee el archivo `.env`. La clave de Anthropic es opcional (el núcleo funciona sin ella) y nunca se muestra en pantalla. La fecha de ejecución se puede fijar para que las pruebas den siempre lo mismo.
- **`.env.example`**: la lista de variables, sin valores secretos. Copiarlo tal cual como `.env` funciona.
- **Calidad automática.** En cada cambio, el CI revisa el estilo (ruff), los tipos (mypy) y las pruebas (pytest). En local todo pasa. En GitHub se verá con el primer *push*.

### Paso 2 · Modelos de datos y validación de insumos
**Objetivo:** describir con Pydantic la solicitud, las plantillas, el maestro, los soportes y el glosario, y detectar los datos rotos antes de procesarlos, sin modificar nunca `datos/`.
**Hecho cuando:** `validar_datos.py` revisa todos los insumos, incluidas las rutas del glosario contra el maestro, y reporta en lenguaje claro los **errores** (dato roto: el CI falla) separados de las **sugerencias** para el dueño del dato (dato mejorable: el CI no falla). Con los datos de ejemplo: 0 errores y la sugerencia de agregar `version` y `actualizado_en` al maestro.
**Estado:** ✅
**Avance:**
- **Moldes de los datos** (`modelos.py`): describen cómo debe ser cada archivo, por ejemplo que el formato sea `xlsx`, `pdf` o `portal`. Los archivos de los casos son estrictos. El maestro es flexible: solo exige razón social y NIT, y lo demás puede faltar.
- **Lectura** (`lectura.py`): lee cada archivo y, si algo está mal, lo explica en español y dice dónde. Por ejemplo: `elemento 3 > «celda_valor»: «C0» no es válido; se espera una celda como «B3»`.
- **Validación** (`validacion.py`): revisa lo que solo se ve mirando varios archivos juntos, como que cada ruta del glosario exista en el maestro o que dos campos no usen la misma celda. Separa los **errores** (dato roto) de las **sugerencias** (dato mejorable).
- **Script** (`validar_datos.py`): muestra el reporte. El CI falla solo si hay errores.
- **Pruebas:** 72 en total. Rompen una copia de los datos, nunca los reales. Resultado con los datos de ejemplo: **0 errores y 1 sugerencia** (agregar la versión al maestro).

### Paso 3 · Base de herramientas y observabilidad
**Objetivo:** crear el contrato común de las herramientas (`Resultado`, decorador `@herramienta` y registro), los logs estructurados y el enmascaramiento de datos sensibles.
**Hecho cuando:** una herramienta de ejemplo valida sus argumentos, nunca lanza excepciones, escribe en `log.jsonl` y enmascara los valores sensibles.
**Estado:** ✅
**Avance:**
- **Un contrato para todas** (`herramientas/base.py`). Cada herramienta responde siempre `{ok, data, error}`. Con poner `@herramienta` encima de una función, esta revisa sus argumentos, nunca lanza una excepción y deja registro.
- **Errores tranquilos.** Un argumento inválido, un dato roto o un fallo inesperado terminan en `ok=False` con un mensaje claro. El detalle técnico va solo al log de operación.
- **Registro de cada llamada** (`observabilidad.py`): una línea en `out/log.jsonl` y otra en `out/<caso>/log.jsonl`, con hora, sesión, herramienta, resultado y resumen.
- **Datos sensibles ocultos:** el número de cuenta y la cédula salen como `****2345` hacia el modelo y en los logs. El NIT no se oculta, porque es de la empresa y es público.
- **Pruebas:** 113 en total. Una herramienta de ejemplo, que solo existe en las pruebas, comprueba todo lo anterior.

## Fase F1 · Núcleo determinista

### Paso 4 · Listado y lectura de solicitudes
**Objetivo:** `proveedor_listar_casos` muestra los casos disponibles (cliente, país y formato), con un filtro opcional, para que el agente identifique "el de Ecuador". `proveedor_leer_solicitud` devuelve el país, el cliente, el formato, los campos y los soportes exigidos de un caso.
**Hecho cuando:** el listado filtra por cliente o país, la lectura responde correctamente en los 4 casos de referencia y ambas devuelven un error claro ante un caso inexistente o una plantilla corrupta.
**Estado:** ✅
**Avance:**
- **`proveedor_listar_casos`**: muestra los casos con su cliente, país, formato y fecha. El filtro no distingue mayúsculas ni tildes: "Ecuador", "EC" y "andina" encuentran el mismo caso. Si coinciden varios, devuelve todos para que el agente pregunte cuál es.
- **`proveedor_leer_solicitud`**: devuelve lo que pide el cliente (país, formato, campos y soportes), con la misma forma para Excel, PDF y portal. En los casos de portal agrega un aviso.
- **Errores claros:** un caso que no existe responde "no existe el caso… Use proveedor_listar_casos". Una plantilla rota dice qué archivo falla y dónde. Un caso roto no impide listar los demás.
- **El correo no se le pasa al modelo:** solo los datos ya extraídos, para evitar instrucciones maliciosas.
- **Pruebas:** 163 en total. Cubren los 4 casos de referencia, los filtros y los errores.

### Paso 5 · Mapeo de campos y su confirmación
**Objetivo:** `proveedor_mapear_campos` clasifica cada campo en `lleno`, `faltante` o `requiere_confirmacion`, en capas (exacto → normalizado → similitud), deja registrados el origen y el método, y guarda el mapeo en `out/<caso>/mapeo.json`. `proveedor_confirmar_campo` resuelve un campo en `requiere_confirmacion` (aceptar o dejar faltante) y registra la decisión en ese mapeo.
**Hecho cuando:** las pruebas unitarias cubren cada capa, ninguna prueba produce un valor que no exista en el maestro y una confirmación cambia el estado del campo sin tocar los demás. *(El bloqueo que obliga a aprobarla en el front se conecta en el Paso 13.)*
**Estado:** ✅
**Avance:**
- **`proveedor_mapear_campos`**: busca cada campo en el glosario en tres capas (exacta → sin mayúsculas ni tildes → parecida) y después su valor en el maestro. Cada campo queda lleno, faltante o por confirmar, con una nota que explica por qué.
- **El resultado se guarda** en `out/<caso>/mapeo.json`, con los valores completos. El modelo, en cambio, ve el número de cuenta y la cédula como `****2345`.
- **`proveedor_confirmar_campo`**: la analista acepta el valor propuesto o deja el campo vacío. Queda registrado quién lo decidió y cuándo, y los demás campos no cambian. Si vuelve a mapear, la decisión se conserva, salvo que el maestro haya cambiado.
- **Nunca se inventa un valor:** el propio modelo de datos rechaza un valor sin fuente, y una prueba revisa que cada valor sea exactamente el del maestro.
- **Con los datos reales:** CO 17 llenos · EC 14 llenos y 1 faltante · HN 10 llenos y 1 faltante · PA 9 llenos. **Pruebas:** 222 en total.

### Paso 6 · Reglas de negocio configurables
**Objetivo:** llevar a `config/reglas.yaml` las reglas de identificador por país, de datos bancarios, de vigencias y "por vencer", y de fecha de ejecución inyectable (RN1–RN8).
**Hecho cuando:** cada regla tiene su prueba, y cambiar un umbral en el YAML cambia el resultado sin tocar el código.
**Estado:** ✅
**Avance:**
- **`config/reglas.yaml`**: los umbrales del mapeo, el identificador de cada país, la lista de datos bancarios y los días de aviso "por vencer". Tiene comentarios para quien lo edite, y si un valor no tiene sentido (por ejemplo, un umbral mayor que 1) da un error claro.
- **RN1 aplicada:** si el cliente no es colombiano, el campo que se llena con el NIT queda **por confirmar**, con la nota "identificador extranjero". Ahora EC, HN y PA tienen 1 campo por confirmar cada uno.
- **Vigencias listas** (RN3 y RN6): cada soporte queda presente, por vencer, vencido o ausente. Los vencidos y los ausentes bloquean la firma. El checklist del Paso 8 las usará.
- **Comprobado de punta a punta:** con `umbral_lleno: 0.95`, el mismo campo pasa de lleno a por confirmar sin tocar el código.
- **Pruebas:** 261 en total.

### Paso 7 · Generación de formularios
**Objetivo:** `proveedor_generar_formulario` produce el Excel en las celdas exactas, el PDF con las etiquetas en orden (o el AcroForm rellenado) y `valores-portal.md` para los portales.
**Hecho cuando:** los tres formatos se generan desde el mapeo guardado (no desde el modelo) y los campos faltantes quedan vacíos y resaltados.
**Estado:** ✅
**Avance:**
- **`proveedor_generar_formulario`**: lee `mapeo.json` (nunca valores del modelo) y genera el Excel, el PDF o `valores-portal.md`, según el formato del cliente. Si el mapeo no existe o no corresponde a la plantilla actual, pide volver a mapear.
- **Excel:** cada etiqueta y su valor en la hoja y la celda exactas, todo como texto (el código postal `050021` conserva su cero) y sin riesgo de que un `=` se ejecute como fórmula.
- **PDF:** los campos en el orden de la plantilla, con `*` en los obligatorios.
- **Portal:** una tabla para copiar, con el aviso "formato no soportado para automatizar".
- **Faltantes y pendientes:** quedan vacíos, en amarillo (falta) o naranja (por confirmar), con una nota que explica por qué. Lo que está por confirmar no se escribe hasta que la analista lo apruebe. **Pruebas:** 291 en total.

### Paso 8 · Paquete para firma
**Objetivo:** `proveedor_armar_paquete` crea la carpeta con el formulario, los soportes, `checklist.md`, `borrador-correo.md` y `manifiesto.json`, y calcula `listo_para_firma`.
**Hecho cuando:** un soporte vencido o ausente bloquea el estado y el borrador nunca contiene datos bancarios.
**Estado:** ✅
**Avance:**
- **`proveedor_armar_paquete`** crea `out/<caso>/paquete/` con:
  - el formulario, generado de nuevo desde el mapeo;
  - los soportes que existen, incluidos los vencidos, para saber cuál renovar;
  - `checklist.md`, `borrador-correo.md` y `manifiesto.json`.
- **Listo para firma** solo si nada lo bloquea. Bloquean un soporte vencido o ausente y un campo por confirmar (decisión de Anderson). Un faltante o un soporte por vencer solo se avisan.
- **El borrador nunca lleva datos bancarios:** la plantilla no los recibe y, además, el texto se revisa antes de guardarlo. Si apareciera uno, el paquete no se arma.
- **El manifiesto** guarda la fecha, la versión del maestro, la huella de cada archivo y el origen de cada campo (quién confirmó), sin valores.
- **A la fecha fija:** CO listo · EC, HN y PA no listos, cada uno con sus motivos. **Pruebas:** 323 en total.

### Paso 9 · Demostración sin modelo y pruebas *golden*
**Objetivo:** `scripts/demo.py` procesa todos los casos llamando directamente a las herramientas, y las pruebas *golden* fijan el resultado esperado de cada caso.
**Hecho cuando:** dos ejecuciones seguidas con la misma fecha dan exactamente el mismo resultado, sin ninguna clave de LLM.
**Estado:** ✅
**Avance:**
- **`scripts/demo.py`**: con un comando procesa los 4 casos por el mismo camino que usará el agente (leer → mapear → generar → armar el paquete) e imprime un resumen. Limpia `out/` al empezar, pero solo si la carpeta se llama `out`.
- **Fecha fija** 2026-09-01 por defecto, con `--fecha hoy` o `--fecha AAAA-MM-DD` para cambiarla.
- **Mismo resultado siempre:** dos ejecuciones dan archivos idénticos byte por byte, salvo los `log.jsonl` (guardan cuánto tardó cada llamada). Para lograrlo, el Excel ahora se genera reproducible.
- **Sin LLM, comprobado:** una prueba ejecuta la demo sin clave y verifica que el SDK de Anthropic nunca se carga.
- **Pruebas golden** en `tests/golden/`: el resumen de la demo y, por caso, el mapeo, el checklist, el borrador, el manifiesto y las celdas del Excel o el texto del PDF. **Pruebas:** 351 en total; la demo también corre en el CI.
- **`--llamadas`** muestra la matriz de casos y herramientas: las 16 llamadas de los 4 casos responden bien (ver el resultado en B4).

## Fase F2 · Agente y chat

### Paso 10 · Adaptador del modelo de lenguaje
**Objetivo:** definir la interfaz `enviar(mensajes, herramientas) → respuesta` (un `Protocol`) y una implementación para el proveedor elegido, con timeout y reintentos.
**Hecho cuando:** existe un adaptador falso para las pruebas y cambiar de proveedor no toca el ciclo del agente.
**Estado:** ✅
**Avance:**
- **Un contrato propio** (`agente/llm/adaptador.py`): `enviar(sistema, mensajes, herramientas) → respuesta`, con nuestros tipos. El modelo responde con texto o con **pedidos de herramienta**: nunca las ejecuta él.
- **Adaptador de Anthropic** (`proveedor_anthropic.py`), con el SDK oficial: timeout de 30 s, 3 reintentos ante fallas pasajeras (los hace el SDK), caché del prompt, esfuerzo `medium` en vez de `temperature` (CA6 ajustada) y errores traducidos a mensajes claros, sin la clave.
- **Modelo falso** (`falso.py`): responde con un guion, para probar el ciclo del Paso 12 sin clave ni costo.
- **Las herramientas que ve el modelo salen solas del registro**: hoy son 6. `proveedor_simular_envio` llega en el Paso 13.
- **Prueba real hecha** con `scripts/probar_modelo.py`. Ante *"¿Qué solicitudes de registro hay? Busca la del cliente de Ecuador"*, el modelo pidió `proveedor_listar_casos` con `{"filtro": "Ecuador"}`: el primer paso correcto. Costó unos USD 0.0003, casi todo por guardar las instrucciones en la caché la primera vez. **Pruebas:** 384 en total, sin red.

### Paso 11 · System prompt y base de conocimiento
**Objetivo:** escribir `agente/prompt.md` (comportamiento) y `knowledge/registro-proveedor.md` (proceso, países y soportes), separados del código y versionados.
**Hecho cuando:** el prompt cubre el flujo, las prohibiciones, el formato del resumen y el trato del correo como datos.
**Estado:** ⬜
**Avance:** _por completar_

### Paso 12 · Ciclo del agente
**Objetivo:** implementar el bucle mensaje → modelo → herramientas → modelo, con tope de iteraciones, tope de tokens por sesión y manejo claro de errores.
**Hecho cuando:** al alcanzar un tope, el agente responde con lo que tiene y lo que falta, y un error del proveedor no cierra la sesión.
**Estado:** ⬜
**Avance:** _por completar_

### Paso 13 · Confirmación humana y envío simulado
**Objetivo:** las herramientas marcadas con aprobación humana (`proveedor_confirmar_campo` y `proveedor_simular_envio`) crean una confirmación pendiente en el servidor y solo se ejecutan tras una aprobación explícita.
**Hecho cuando:** ninguna prueba consigue escribir `ENVIO-SIMULADO.md` ni confirmar un campo sin aprobación, aunque el modelo lo intente.
**Estado:** ⬜
**Avance:** _por completar_

### Paso 14 · Guardarraíles
**Objetivo:** que el modelo reciba los datos sensibles enmascarados, que la respuesta se revise contra los valores que salieron de las herramientas y que el contenido del correo quede delimitado como datos.
**Hecho cuando:** un correo con instrucciones maliciosas no provoca ninguna acción y un valor inventado en la respuesta se detecta.
**Estado:** ⬜
**Avance:** _por completar_

### Paso 15 · API
**Objetivo:** exponer con FastAPI `/api/chat`, `/api/confirmations/{id}`, `/api/sessions/{id}` y `/api/health`, documentados en OpenAPI.
**Hecho cuando:** las pruebas de contrato pasan y ninguna respuesta expone claves ni datos completos.
**Estado:** ⬜
**Avance:** _por completar_

### Paso 16 · Front de chat
**Objetivo:** mostrar el historial, el indicador "pensando", cada llamada a herramienta (nombre, argumentos y resumen), los botones Aprobar / Rechazar y botones de copiar valor.
**Hecho cuando:** la usuaria procesa un caso completo desde el navegador sin usar la terminal.
**Estado:** ⬜
**Avance:** _por completar_

## Fase F3 · Despliegue y operación

### Paso 17 · Evaluaciones del agente
**Objetivo:** crear conversaciones guionadas que verifiquen las herramientas llamadas, que no haya valores inventados, que se pida la confirmación y que se resista la inyección de prompts.
**Hecho cuando:** existe un reporte de evaluaciones por versión del prompt y del modelo.
**Estado:** ⬜
**Avance:** _por completar_

### Paso 18 · Seguridad y control de costos
**Objetivo:** proteger el acceso, poner topes de sesiones por día y registrar los tokens y el costo estimado por caso.
**Hecho cuando:** un usuario no puede gastar la clave sin límite y el costo por caso queda medido.
**Estado:** ⬜
**Avance:** _por completar_

### Paso 19 · Contenedor y despliegue
**Objetivo:** construir una imagen Docker y desplegarla en un servicio administrado, con los secretos fuera del código y un health check.
**Hecho cuando:** la URL responde, `/api/health` está en verde y un `docker compose up` local levanta todo en menos de 2 minutos.
**Estado:** ⬜
**Avance:** _por completar_

### Paso 20 · Módulo reutilizable
**Objetivo:** empaquetar el agente para que otras plataformas lo usen sin depender del servidor: las herramientas como **servidor MCP**, el prompt como `agent.md` y el conocimiento como `SKILL.md`.
**Hecho cuando:** las tres piezas son **las mismas** que usa la aplicación (sin copias divergentes) y un cliente MCP puede llamar a las herramientas.
**Estado:** ⬜
**Avance:** _por completar_

### Paso 21 · Piloto con la usuaria
**Objetivo:** procesar solicitudes reales con la analista, medir el tiempo y los errores frente al proceso manual y recoger mejoras.
**Hecho cuando:** hay métricas del piloto y una lista priorizada de ajustes.
**Estado:** ⬜
**Avance:** _por completar_

---

# Parte B · Documentación de la solución

> Se completa a medida que se cierran los pasos de la Parte A. Las secciones siguen el mismo orden de construcción, y cada una indica de qué pasos se alimenta: cuando se cierra uno de esos pasos, se actualiza la sección.

| Sección | Se alimenta de |
|---|---|
| B1 Problema en una frase | Plan · Paso 21 |
| B2 Arquitectura | Pasos 1, 2, 3, 10, 15, 16 |
| B3 Núcleo determinista | Pasos 4, 5, 6, 7, 8 |
| B4 Calidad y pruebas | Pasos 9, 17 |
| B5 Elección del modelo y costo | Pasos 10, 18 |
| B6 Ciclo del agente y confirmación humana | Pasos 11, 12, 13 |
| B7 Seguridad y guardarraíles | Pasos 3, 14, 18 |
| B8 Diseño para portales web | Paso 7 · Plan §14 |
| B9 Operación y despliegue | Pasos 1, 9, 19 |
| B10 Módulo reutilizable | Paso 20 |
| B11 Resultados del piloto | Paso 21 |
| B12 Cobertura de historias de usuario | Pasos 3–13 |
| B13 Decisiones y trade-offs | Todos |
| B14 Supuestos | Todos |
| B15 Riesgos para producción | Pasos 14, 17, 18, 21 |
| B16 Uso de IA en la construcción | Todos |

## B1 · Problema en una frase
**Se alimenta de:** el plan, y el Paso 21 si el piloto lo reformula.
**Objetivo:** decir en una línea qué se resuelve y a quién le duele.
_por completar_

## B2 · Arquitectura
**Se alimenta de:** Pasos 1, 2, 3, 10, 15 y 16.
**Objetivo:** mostrar el diagrama front → API → agente → herramientas → dominio → archivos, las capas y sus responsabilidades, y dónde viven el prompt, el conocimiento y la ejecución.

**Lo que existe hasta ahora (pasos 1 a 3):**

```
 agente (Paso 12) / demo.py (Paso 9)
        │  pide una herramienta
        ▼
 herramientas/base.py ── revisa argumentos · nunca lanza · registra · oculta lo sensible
        │                     └─ escribe en out/log.jsonl
        ▼
 dominio/  lectura.py → modelos.py      validacion.py → validar_datos.py (CI)
        │
        ▼
 datos/ (solo lectura)
```

| Parte | Qué hace, en una frase |
|---|---|
| `config.py` | Es el único lugar donde se lee la configuración (`.env`). |
| `dominio/modelos.py` | Describe cómo debe ser cada dato. No lee archivos. |
| `dominio/lectura.py` | Lee un archivo y lo convierte en un dato confiable, o explica qué está mal. |
| `dominio/validacion.py` | Revisa todos los datos juntos y arma el reporte. |
| `herramientas/base.py` | El contrato común: `Resultado`, `Contexto`, `@herramienta` y `Registro`. |
| `observabilidad.py` | El registro de llamadas (`log.jsonl`), los logs de operación y el enmascaramiento. |

**Una regla importante:** dentro del dominio, un dato roto genera un error (`ErrorDeDatos`). La herramienta lo atrapa y responde `ok=False` con el mensaje, así que el agente nunca se cae por un error.

**Dos formas de llamar a una herramienta:**
- **Desde Python** (demo.py y pruebas): recibe los datos completos y con su tipo.
- **Desde el agente:** por nombre y con un diccionario, que se valida antes de ejecutar. Lo que el agente recibe sale con `a_json()`, que oculta los datos sensibles.

**Glosario rápido:**

| Término | Qué es |
|---|---|
| **uv** | Instala Python y las librerías del proyecto. |
| **Pydantic** | Revisa que un dato tenga la forma esperada, como una aduana. |
| **ruff** | Revisa el estilo del código y lo ordena. |
| **mypy** | Revisa que los tipos de datos sean coherentes antes de ejecutar el código. |
| **pytest** | Ejecuta las pruebas automáticas. |
| **CI** | Ejecuta todas esas revisiones solo, cada vez que se sube un cambio. |
| **Fixture** | Algo que una prueba necesita y que pytest prepara antes, como una copia de `datos/`. |
| **Decorador** | Una "envoltura" que se pone encima de una función (`@herramienta`) para agregarle comportamiento. |
| **structlog** | La librería de los logs de operación, que los escribe en JSON. |

**El adaptador del modelo (Paso 10):**

```
agente (Paso 12)
   │  enviar(sistema, conversación, herramientas)
   ▼
AdaptadorLLM  ◀── contrato propio: el agente solo conoce esto
   ├── AdaptadorAnthropic  → SDK oficial → API de Claude
   └── AdaptadorFalso      → guion fijo (pruebas, sin clave ni costo)
```

| Parte | Qué hace, en una frase |
|---|---|
| `agente/llm/adaptador.py` | Nuestros tipos (mensaje, texto, pedido de herramienta, resultado, respuesta) y el contrato `AdaptadorLLM`. |
| `agente/llm/proveedor_anthropic.py` | Traduce entre nuestros tipos y los de Anthropic, y los errores del SDK a mensajes claros. |
| `agente/llm/falso.py` | Un modelo con guion, para probar el agente sin red. |

**Cambiar de proveedor** = escribir otra clase con `modelo` y `enviar`. El ciclo del agente no cambia.

_El resto se completa en los pasos 15 y 16._

## B3 · Núcleo determinista: lectura, mapeo, reglas y generación
**Se alimenta de:** Pasos 4, 5, 6, 7 y 8.
**Objetivo:** explicar cómo se lee una solicitud, cómo funciona el mapeo en capas y sus niveles de confianza, dónde están configuradas las reglas de negocio y cómo se generan el formulario y el paquete.

**1. Encontrar y leer el caso (Paso 4)**

```
"procesa el de Ecuador"
   │
   ▼
proveedor_listar_casos(filtro="Ecuador") ──▶ ec-corp-andina
   │
   ▼
proveedor_leer_solicitud(caso="ec-corp-andina")
   └─▶ país EC · formato pdf · 15 campos · 5 soportes exigidos
```

| Parte | Qué hace, en una frase |
|---|---|
| `dominio/texto.py` | Normaliza el texto para comparar: "Panamá" → "panama". |
| `dominio/casos.py` | Lista y lee los casos. Es la lógica, sin nada del agente. |
| `herramientas/proveedor.py` | Las herramientas reales: envolturas delgadas sobre `casos.py`. |

**Cómo funciona el filtro:** cada palabra del filtro debe aparecer en el caso, el cliente o el país. Una palabra de 4 letras o más vale si es el comienzo de otra ("indus" encuentra "industrias"). Las más cortas deben ser exactas, para que "CO" (Colombia) no encuentre "corp" (el caso de Ecuador).

**Los campos tienen la misma forma en todos los formatos:** etiqueta, si es obligatorio y, en Excel, la hoja y la celda. Las plantillas de Excel no dicen si un campo es obligatorio, así que ese dato queda vacío en lugar de inventarse.

**2. Mapear los campos (Paso 5)**

Para cada campo, primero se busca la etiqueta en el glosario y después el valor en el maestro:

```
"Nombre de la empresa" ──glosario──▶ razon_social ──maestro──▶ "Empresa Ejemplo S.A.S."
```

| Capa | Ejemplo | Confianza | Resultado |
|---|---|---|---|
| 1. Exacta | "Razón social" | 1.0 | lleno |
| 2. Sin mayúsculas, tildes ni signos | "RAZON SOCIAL:" | 0.95 | lleno |
| 3. Parecida | "Razon socail" (92 %) | el puntaje | lleno si es ≥ 0.9 · por confirmar si está entre 0.8 y 0.9 · faltante si es menor |

- **Si el maestro no tiene el dato**, el campo queda **faltante**. Nunca se rellena con otra cosa.
- **Si una etiqueta se parece igual a dos datos distintos**, queda **por confirmar**.
- **La medida de parecido es prudente a propósito:** compara las frases completas. Una más permisiva diría que "Cédula del representante legal" es igual a "Representante legal" y llenaría la cédula con el nombre.
- **Todo queda en `mapeo.json`:** es la fuente que usará el generador de formularios (Paso 7), así que el modelo nunca le pasa valores a otra herramienta.

**3. Reglas de negocio (Paso 6)**

Las reglas que el negocio puede querer cambiar viven en `config/reglas.yaml`. Por ejemplo, para avisar 30 días antes de un vencimiento en vez de 15, se cambia un número en ese archivo.

| Regla | Qué hace | Dónde vive |
|---|---|---|
| RN1 · Identificador por país | Cliente extranjero → el campo con el NIT queda **por confirmar** ("identificador extranjero"). | `reglas.yaml` + mapeo |
| RN2 · Datos bancarios | Se llenan solo si la plantilla los pide y **nunca** van en el borrador del correo. | `reglas.yaml` (lo usa el Paso 8) |
| RN3 · Qué bloquea la firma | Un soporte vencido o ausente bloquea; un campo faltante, no. | `dominio/reglas.py` |
| RN4 · Nada sale sin aprobación | La confirmación la controla el servidor. | Paso 13 |
| RN5 · Registro de cada llamada | `out/log.jsonl` y `out/<caso>/log.jsonl`. | `observabilidad.py` (Paso 3) |
| RN6 · Por vencer | Vence en 15 días o menos → se avisa, no bloquea. | `reglas.yaml` |
| RN7 · Fecha inyectable | Las pruebas usan una fecha fija. | `.env` (`FECHA_EJECUCION`) |
| RN8 · Datos sensibles | Cuenta y cédula como `****2345`. | **En el código**, a propósito (D23) |

**Ejemplo con las fechas.** Hoy (24 de noviembre de 2026) la Cámara de Comercio ya está vencida: venció el 30 de septiembre. Por eso las pruebas usan el 1 de septiembre de 2026. Con esa fecha, la Cámara está vigente, los parafiscales vencidos bloquean el caso de Honduras y el certificado tributario ausente bloquea el de Ecuador.

**4. Generar el formulario (Paso 7)**

```
out/<caso>/mapeo.json ──▶ proveedor_generar_formulario ──▶ formulario.xlsx | formulario.pdf | valores-portal.md
```

| Estado del campo | En el formulario |
|---|---|
| lleno | el valor |
| faltante | vacío, **amarillo**, con la nota "Falta: …" |
| por confirmar | vacío, **naranja**, con la nota "Pendiente de confirmación: …" |

| Archivo | Qué hace, en una frase |
|---|---|
| `generadores/comun.py` | Decide qué se escribe en cada campo y comprueba que el mapeo sea de la plantilla actual. |
| `generadores/excel.py` | Escribe cada etiqueta y su valor en la celda exacta, siempre como texto. |
| `generadores/pdf.py` | Arma una tabla etiqueta/valor en el orden de la plantilla. |
| `generadores/portal.py` + `plantillas/valores-portal.md.j2` | Arma la tabla para copiar en el portal (el texto vive en la plantilla de Jinja2). |

**Por qué nunca desde el modelo:** el formulario sale solo de `mapeo.json`, así que el modelo no puede cambiar un valor entre "mapear" y "generar". La respuesta al modelo trae la ruta y los conteos, sin ningún valor.

**5. Armar el paquete para firma (Paso 8)**

```
out/<caso>/paquete/
├── formulario.xlsx | .pdf | valores-portal.md   (generado de nuevo desde mapeo.json)
├── <soportes>.txt                               (copias; los vencidos también)
├── checklist.md                                 (listo o no, y por qué)
├── borrador-correo.md                           (sin datos bancarios)
└── manifiesto.json                              (para auditar: huellas y origen de cada campo)
```

| ¿Bloquea la firma? | Ejemplo |
|---|---|
| ⛔ Sí | Soporte **vencido** (parafiscales de Honduras), soporte **ausente** (certificado tributario de Ecuador), campo **por confirmar** (el RUC). |
| ⚠️ No, solo se avisa | Campo **faltante** en el maestro, soporte **por vencer** (15 días o menos). |

**A la fecha fija (1 de septiembre de 2026):** CO ✅ listo · EC ⛔ (falta un soporte y el RUC está por confirmar) · HN ⛔ (parafiscales vencidos y RTN por confirmar) · PA ⛔ (solo el RUC por confirmar; al aceptarlo, queda listo).

**Dos protecciones para el borrador (RN2):**
1. La plantilla del correo no recibe ningún dato bancario.
2. Antes de guardarlo, se revisa el texto. Si aparece el número de cuenta, el SWIFT o la cédula, el paquete no se arma. Un dato bancario que también es público, como el titular de la cuenta (que es la razón social), sí puede aparecer.

**El paquete se arma completo o no se arma:** primero se crea en una carpeta temporal y, solo si todo salió bien, reemplaza al anterior.

## B4 · Calidad y pruebas
**Se alimenta de:** Pasos 9 y 17.
**Objetivo:** describir la estrategia de pruebas (unitarias, *golden*, `demo.py` y evaluaciones del agente), qué cubre cada nivel, cómo corren en el CI y los resultados obtenidos.

| Nivel | Qué cubre | Dónde |
|---|---|---|
| **Unitarias** | Cada pieza por separado: lectura y validación de datos, mapeo y sus capas, reglas, generadores, paquete, herramientas y observabilidad. Muchas rompen una **copia** de los datos a propósito, para ver que el error se detecta con un buen mensaje. | `tests/unit/` |
| **Golden** | El resultado completo de cada caso, comparado con lo guardado: mapeo, checklist, borrador, manifiesto y celdas del Excel o texto del PDF. Si algo cambia sin querer, muestra la diferencia línea por línea. | `tests/golden/` |
| **Demo** | Los 4 casos de punta a punta, sin LLM, con un comando. También comprueba que dos ejecuciones den lo mismo. | `scripts/demo.py` |
| **Evaluaciones del agente** | Conversaciones guionadas con el modelo real (Paso 17). | pendiente |

**Garantías que tienen su propia prueba:**
- **Nunca se inventa un valor:** cada valor del formulario es exactamente el del maestro.
- **Lo sensible no sale:** el número de cuenta y la cédula nunca aparecen completos en lo que ve el modelo, en los logs ni en el borrador.
- **Las herramientas nunca lanzan:** ni con argumentos malos, ni con datos rotos, ni con un error inesperado.
- **`datos/` nunca se modifica.**
- **Mismo resultado siempre** con la misma fecha.

**Cómo se ejecutan:**

```powershell
uv run pytest                        # todas: unitarias y golden
uv run pytest --actualizar-golden    # después de un cambio intencional; revisar con git diff
```

**En el CI**, en cada cambio: ruff → mypy → pytest → `validar_datos.py` → `demo.py`.

**Resultado actual:** 351 pruebas en verde.

**Resultado de la demo con los datos de ejemplo** (`demo.py --llamadas`, fecha fija 2026-09-01). Es lo que hará el agente con cada caso, antes de conectar el modelo. Primero se llama `proveedor_listar_casos` → ✓ 4 casos.

| Caso | 1. Leer solicitud | 2. Mapear campos | 3. Generar formulario | 4. Armar paquete |
|---|---|---|---|---|
| co-industrias-delta | ✓ xlsx · 17 campos · 4 soportes | ✓ 17 llenos · 0 faltantes · 0 por confirmar | ✓ formulario.xlsx | ✓ listo para firma |
| ec-corp-andina | ✓ pdf · 15 campos · 5 soportes | ✓ 13 llenos · 1 faltante · 1 por confirmar | ✓ formulario.pdf | ✓ NO listo (2 motivos) |
| hn-agroexport-sula | ✓ xlsx · 11 campos · 3 soportes | ✓ 9 llenos · 1 faltante · 1 por confirmar | ✓ formulario.xlsx | ✓ NO listo (2 motivos) |
| pa-logistica-istmo | ✓ portal · 9 campos · 2 soportes | ✓ 8 llenos · 0 faltantes · 1 por confirmar | ✓ valores-portal.md | ✓ NO listo (1 motivo) |

✓ = la herramienta respondió bien. "NO listo" es el resultado correcto, no un error. EC tiene un soporte ausente y el RUC por confirmar, HN tiene parafiscales vencidos y el RTN por confirmar, y PA solo tiene el RUC por confirmar.

## B5 · Elección del modelo y costo
**Se alimenta de:** Pasos 10 y 18.
**Objetivo:** indicar el proveedor y el modelo, por qué se eligieron, cómo se cambia de proveedor gracias al adaptador y el costo real medido por caso procesado.

| Tema | Decisión |
|---|---|
| Proveedor | **Anthropic**, con su SDK oficial (`anthropic`). |
| Modelo | **`claude-haiku-5-5`**: el más económico (USD 0.10 por millón de tokens de entrada y 0.50 de salida). El modelo no calcula valores: solo elige herramientas y redacta, porque el núcleo es determinista (principio 1). Se cambia con `LLM_MODELO`, sin tocar código. |
| Esfuerzo | `medium` (`LLM_ESFUERZO`). Reemplaza a `temperature`, que este modelo y la versión actual de la API rechazan (CA6, ajustada). En el Paso 17 se mide si `low` alcanza. |
| Caché | Activada: el prompt y las herramientas se repiten en cada llamada y, desde la segunda, se cobran mucho más barato. |
| Fallas | Timeout de 30 s y 3 reintentos ante fallas pasajeras (los hace el SDK). |
| Cambiar de proveedor | Una clase nueva que cumpla `AdaptadorLLM` (ver B2). |

**Costo:** se medirá por caso procesado en el Paso 18. Cada respuesta ya registra los tokens de entrada, de salida y de caché.

**Primera llamada real (Paso 10):** 4 tokens de entrada, 60 de salida y 2056 guardados en la caché (las instrucciones y las 6 herramientas): unos **USD 0.0003**. Guardar en caché cuesta 1.25 veces la entrada; leer de ella, 0.1 veces. Por eso, desde la segunda llamada de una conversación, esa parte cuesta mucho menos.

## B6 · Ciclo del agente y confirmación humana
**Se alimenta de:** Pasos 11, 12 y 13.
**Objetivo:** explicar el bucle mensaje → modelo → herramientas, los topes de iteraciones y de tokens, el manejo de errores, la separación entre prompt y conocimiento, y la confirmación humana controlada por el servidor.
_por completar_

## B7 · Seguridad y guardarraíles
**Se alimenta de:** Pasos 3, 14 y 18.
**Objetivo:** documentar el manejo de secretos, el enmascaramiento de datos sensibles, los datos mínimos que se envían al modelo, la defensa contra la inyección de prompts, la verificación de valores, la protección del acceso y los topes de costo.

**Lo que hay hasta ahora (pasos 1 a 3):**

| Riesgo | Cómo se cubre |
|---|---|
| Que se filtre la clave de Anthropic | Vive solo en `.env` (que no se sube a git) y se guarda como `SecretStr`: si se imprime, se ve `**********`. |
| Que el modelo o un log vean la cuenta o la cédula completas | Salen como `****2345`. Todo lo que va al modelo pasa por `a_json()` y todo log pasa por el enmascaramiento. |
| Que un error técnico muestre datos o rutas del computador | El modelo solo recibe un mensaje corto. El detalle va al log de operación, sin los valores de las variables. |
| Que se pida un caso como `../secreto` para salir de la carpeta | El nombre se valida con un patrón y, además, se comprueba que la ruta final quede dentro de `datos/` o de `out/`. |
| Que el modelo invente argumentos (`{"enviar": true}`) | Se rechazan: los argumentos no aceptan campos desconocidos. |

**Paso 5:** en el mapeo, el valor de un campo como "Número de cuenta" se oculta según su **ruta en el maestro** (`es_ruta_sensible`), porque en la respuesta ese dato se llama `valor`, no `numero_cuenta`.

**Lo que falta:** el Paso 14 agrega la revisión de la respuesta del modelo y la defensa contra correos maliciosos. El Paso 18 agrega la protección del acceso y los topes de costo.

## B8 · Diseño para portales web
**Se alimenta de:** Paso 7 y la sección 14 del plan.
**Objetivo:** resumir lo implementado (valores para copiar y adjuntos) y el diseño del navegador asistido: credenciales, límites y reparto de tareas entre el agente y la persona.

**Lo implementado (MVP):** para un cliente con portal, el agente genera `out/<caso>/valores-portal.md`, una tabla "campo → valor" lista para copiar, y avisa que el portal no se automatiza. Lo que falta o está por confirmar se marca en la tabla y se lista al final. Los soportes que se deben adjuntar llegan con el paquete del Paso 8.

**Lo que sigue (fase F4, diseño):**

| Tema | Propuesta |
|---|---|
| Cómo | Un navegador asistido (Playwright, en modo visible): el agente llena los campos y la persona mira. |
| Credenciales | Las escribe **la persona** directamente en el navegador, o salen de un gestor de contraseñas corporativo. Nunca van en el repositorio, el prompt ni los logs, y el agente nunca las ve. |
| Límites | CAPTCHA, MFA y cambios de diseño del portal. El agente **no** resuelve CAPTCHAs: lo hace la persona. La ubicación de cada campo en cada portal se guarda en archivos de configuración versionados y se prueba periódicamente. |
| Reparto de tareas | El agente navega y llena. La persona ingresa las credenciales, revisa y hace clic en **"Enviar"**. |
| Evidencia | Una captura de pantalla antes de enviar, guardada en el manifiesto del paquete. |

## B9 · Operación y despliegue (README)
**Se alimenta de:** Pasos 1, 9 y 19.
**Objetivo:** explicar cómo levantarlo en local con un comando, qué variables de entorno necesita, cómo correr `demo.py` y las pruebas, cómo se despliega y cuál es la URL.

**Instalación local (Paso 1):**

```powershell
uv sync                                  # crea .venv e instala lo de uv.lock
copy .env.example .env                   # luego, si se usará el LLM, poner la clave en .env
uv run pytest                            # pruebas
uv run ruff check . ; uv run ruff format --check . ; uv run mypy src   # calidad
```

**Variables de entorno:**

| Variable | Obligatoria | Por defecto | Para qué |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | No (solo para el chat) | — | Clave del modelo. Solo en `.env` o en el gestor de secretos. |
| `LLM_MODELO` | No | `claude-haiku-5-5` | Modelo de lenguaje. |
| `FECHA_EJECUCION` | No | Fecha de hoy | Fecha fija `AAAA-MM-DD` para pruebas y demostraciones (RN7). |
| `NIVEL_LOG` | No | `INFO` | `DEBUG`, `INFO`, `WARNING` o `ERROR`. |

**CI:** `.github/workflows/ci.yml` corre en cada *push* los mismos comandos de calidad, con `uv sync --locked` (falla si `uv.lock` está desactualizado).

**Demostración sin modelo (Paso 9):**

```powershell
uv run python scripts/demo.py                          # los 4 casos, fecha fija 2026-09-01
uv run python scripts/demo.py --fecha hoy              # con la fecha real
uv run python scripts/demo.py --caso ec-corp-andina    # un solo caso
uv run python scripts/demo.py --llamadas               # + matriz de llamadas a herramientas
```

- No necesita clave de Anthropic.
- Con `--llamadas`, al final muestra una **matriz**: una fila por caso y una columna por herramienta, en el orden en que se llaman (leer → mapear → generar → armar el paquete). Cada celda dice ✓ o ✗ y lo esencial de la respuesta. También la guarda en `out/llamadas.md`. Es la misma secuencia que hará el agente con el modelo, y queda fijada en las pruebas golden.
- Borra y vuelve a crear `out/`, y deja ahí, por caso, el mapeo, el formulario y el paquete para firma.
- Termina con código 0 si todo salió bien. Un caso "no listo para firma" no es un error.
- Con la fecha de hoy, ningún caso está listo, porque la Cámara de Comercio venció el 30 de septiembre.

_El despliegue y la URL se completan en el Paso 19._

## B10 · Módulo reutilizable
**Se alimenta de:** Paso 20.
**Objetivo:** describir cómo se empaquetó el agente (servidor MCP, `agent.md` y `SKILL.md`), cómo se conecta desde otra plataforma y cómo se garantiza que usa las mismas piezas que la aplicación.
_por completar_

## B11 · Resultados del piloto
**Se alimenta de:** Paso 21.
**Objetivo:** registrar las métricas del piloto frente al proceso manual (tiempo por solicitud, porcentaje de campos llenados automáticamente, errores, costo), la retroalimentación de la usuaria y los ajustes priorizados.
_por completar_

## B12 · Cobertura de historias de usuario
**Se alimenta de:** Pasos 3 a 13.
**Objetivo:** dejar el estado de cada historia, los pasos que la implementan y lo que falta para producción.

| Historia | Pasos | Estado | Qué falta para producción |
|---|---|---|---|
| HU-1 Leer la solicitud | 4, 6 | ✅ | Para producción: probar con plantillas reales, que serán más desordenadas que las de ejemplo. |
| HU-2 Mapear campos | 5, 6 | 🟨 | Hecho: capas, estados, regla de país, origen por campo, confirmación registrada y nunca un valor inventado. Falta que la confirmación exija aprobar en el front (Paso 13). |
| HU-3 Generar formulario | 7 | 🟨 | Hecho: Excel en celdas exactas, PDF en orden y valores para portal, siempre desde el mapeo, con los faltantes vacíos y resaltados. Falta rellenar un PDF AcroForm del cliente y escribir sobre su `.xlsx` original (ningún caso de ejemplo los trae). |
| HU-4 Paquete para firma | 8 | 🟨 | Hecho: carpeta con formulario, soportes, checklist (presente, ausente, vencido o por vencer), borrador sin datos bancarios y `listo_para_firma`. Falta que el agente cierre con un resumen y una pregunta explícita (pasos 11 y 12). |
| HU-5 Envío con confirmación | 13 | ⬜ | |
| HU-6 Manejo de errores | 3, 12 | 🟨 | Hecho para las herramientas (nunca lanzan; mensaje claro). Falta el error del proveedor del LLM (Paso 12). |
| HU-7 Trazabilidad | 3, 8 | ✅ | Hecho: `log.jsonl` por llamada y `manifiesto.json` con fecha, versión del maestro, huellas y origen de cada campo. Para producción: registrar también la versión del prompt (Paso 11) y pedir que el maestro tenga versión. |

## B13 · Decisiones y trade-offs
**Se alimenta de:** todos los pasos.
**Objetivo:** registrar cada decisión con la alternativa descartada y el porqué. Se parte de la sección 15 del plan y se agregan las que surjan al construir.

| # | Decisión | Alternativa descartada | Por qué | Paso |
|---|---|---|---|---|
| D7 | Instalar todas las dependencias del stack desde el Paso 1. | Agregarlas a medida que se usan. | El stack ya está decidido, se instala una sola vez y `uv.lock` queda estable. | 1 |
| D8 | La API key es opcional en la configuración. | Hacerla obligatoria. | El núcleo y `demo.py` deben funcionar sin LLM (principio 7). | 1 |
| D9 | Las variables vacías del `.env` cuentan como ausentes (`env_ignore_empty`). | Exigir que se borren las líneas vacías. | Copiar `.env.example` tal cual no debe romper el arranque. | 1 |
| D10 | ruff no revisa los `.md`. | Formatear también los ejemplos de código de los documentos. | Los ejemplos del plan son ilustrativos, no código ejecutable. | 1 |
| D11 | `datos/` no se modifica; lo que le falta se reporta como **sugerencia** para el dueño del dato. | Completar a mano `maestro.json` (por ejemplo, con `version`). | Los datos son la entrada real del proceso: el sistema debe convivir con datos incompletos y decir qué falta, no esconderlo. | 2 |
| D12 | El validador separa **errores** (bloquean) de **sugerencias** (no bloquean). | Un solo nivel de error. | Un dato mejorable no debe detener el proceso ni el CI, pero tampoco debe pasar en silencio. | 2 |
| D13 | Modelo `Maestro` fijo para los campos conocidos y tolerante con los nuevos. | Fijo estricto (`extra="forbid"`) o totalmente flexible. | El estricto haría fallar todo el maestro por un campo nuevo; el flexible no detectaría errores de tipo. Así se valida lo conocido y lo nuevo se sugiere revisar. | 2 |
| D14 | El NIT no se enmascara; la cuenta bancaria y la cédula del representante, sí. | Enmascarar también el NIT. | RN8 habla de identificaciones **personales**. El NIT es de la empresa, es público y el resumen lo necesita. | 3 |
| D15 | Dos logs: la auditoría (`log.jsonl`) y la operación (structlog). | Un solo log para todo. | Responden preguntas distintas: "¿qué hizo el agente?" frente a "¿por qué falló?". El detalle técnico no debe mezclarse con la auditoría. | 3 |
| D16 | El enmascaramiento se aplica al salir (`a_json()` y los logs), y la llamada desde Python recibe los datos completos. | Enmascarar dentro de cada herramienta. | Una sola puerta de salida es más difícil de olvidar. demo.py y los generadores necesitan los valores reales para escribir los archivos. | 3 |
| D17 | El argumento `requiere_confirmacion` ya existe en `@herramienta`, aunque todavía no bloquea nada. | Agregarlo en el Paso 13. | Las herramientas de los pasos 4 a 8 nacen con la marca correcta y el Paso 13 solo agrega el bloqueo. | 3 |
| D18 | `proveedor_leer_solicitud` no devuelve el cuerpo del correo. | Pasarle el correo completo al modelo. | El correo es contenido externo y puede traer instrucciones maliciosas. Lo necesario ya se extrae sin el modelo. | 4 |
| D19 | En el filtro, las palabras de menos de 4 letras deben coincidir exactas. | Buscar cualquier coincidencia parcial. | Con coincidencia parcial, "CO" (Colombia) encontraría "corp" (el caso de Ecuador). | 4 |
| D20 | El parecido se mide con `token_sort_ratio` (frases completas). | `token_set_ratio` o `ratio`. | Se probaron las tres con etiquetas reales. `token_set` llenaría la cédula con el nombre, y `ratio` propondría el cargo como nombre del representante. | 5 |
| D21 | La confirmación guarda el valor que se le propuso a la analista. | Guardar solo la decisión. | Permite cambiar de opinión y, al volver a mapear, saber si la propuesta sigue siendo la misma que ella aprobó. | 5 |
| D22 | En el mapeo, lo sensible se oculta según la ruta del maestro, en la herramienta. | Confiar en el enmascaramiento por nombre de campo. | El número de cuenta viene en un campo llamado `valor`: el enmascaramiento por nombre no lo vería. | 5 |
| D23 | La lista de datos sensibles (RN8) queda en el código, no en `reglas.yaml`. | Hacerla configurable. | Es seguridad, no negocio: borrar una línea del YAML por error dejaría expuesta la cuenta bancaria. | 6 |
| D24 | `reglas.yaml` se lee en cada llamada a la herramienta. | Leerlo una sola vez al arrancar. | Un cambio en las reglas se nota en el siguiente mapeo, sin reiniciar. Leer un archivo pequeño cuesta casi nada. | 6 |
| D25 | La decisión de la analista queda solo en `confirmacion`; la nota no se toca. | Agregar "aceptado por..." al final de la nota. | La nota explica por qué se preguntó (por ejemplo, la de RN1). Mezclarla con la decisión complicaba cambiar de opinión. | 6 |
| D26 | Un campo por confirmar queda **vacío** en el formulario hasta que se apruebe. | Escribir el valor propuesto. | Un valor no aprobado no debe aparecer en un documento que va a firma. Después de confirmar, se vuelve a generar. | 7 |
| D27 | `celda_etiqueta` es obligatoria en `mapeo.json` (sin valor por defecto). | Darle un valor por defecto vacío. | Un mapeo viejo falla al leerse y la herramienta pide volver a mapear, en vez de generar un Excel sin etiquetas. | 7 |
| D28 | En el Excel, todo se escribe como texto y un `=` no se vuelve fórmula. | Dejar que Excel adivine el tipo. | Excel quitaría el cero de "050021" y podría ejecutar una fórmula maliciosa al abrir el archivo. | 7 |
| D29 | El PDF rellenable (AcroForm) queda pendiente. | Implementarlo sin un archivo para probar. | Ningún caso de ejemplo trae un AcroForm: sería código que nadie puede verificar. | 7 |
| D30 | Un campo por confirmar **bloquea** `listo_para_firma` (decisión de Anderson). | Que solo bloqueen los soportes, como dice RN3. | Su celda está vacía en el formulario (D26) y la decisión está en manos de la analista. Un faltante no bloquea porque no hay nada que decidir. | 8 |
| D31 | El formulario se genera de nuevo al armar el paquete. | Copiar el que generó el Paso 7. | Así nunca va a firma un formulario viejo, por ejemplo uno de antes de confirmar el RUC. | 8 |
| D32 | RN2 tiene dos protecciones: la plantilla no recibe datos bancarios y el texto se revisa antes de guardarlo. | Confiar solo en la plantilla. | Un dato podría llegar por otro lado, como el asunto del correo del cliente. Los valores que también son públicos (el titular = la razón social) no se consideran secretos. | 8 |
| D33 | El paquete se arma en una carpeta temporal y reemplaza al anterior al final. | Escribir directo en `paquete/`. | Nunca queda un paquete a medias ni archivos sobrantes de una versión anterior. | 8 |
| D34 | El Excel se hace reproducible (fechas fijas dentro del archivo) y todo el texto se escribe con saltos de línea `\n`. | Aceptar que el Excel y las huellas cambien en cada ejecución. | El plan pide "exactamente el mismo resultado". Además, así el resultado es igual en Windows y en Linux (el CI). | 9 |
| D35 | Los golden comparan el Excel por sus celdas, el PDF por su texto, y sin las huellas de los archivos binarios. | Comparar los archivos byte por byte. | La compresión puede variar entre sistemas. Que las huellas no cambien en la misma máquina se prueba aparte. | 9 |
| D36 | La demo solo borra una carpeta que se llame `out`. | Borrar la carpeta que se le indique. | Un `--salida` mal escrito no puede borrar algo valioso. | 9 |
| D37 | Tipos propios para la conversación, no los del SDK de Anthropic. | Usar directamente los tipos del SDK. | D3: cambiar de proveedor no debe tocar el ciclo del agente. Solo el adaptador conoce los tipos de Anthropic. | 10 |
| D38 | Sin `temperature`; la consistencia la dan el núcleo determinista y el esfuerzo (CA6 ajustada, con aprobación de Anderson). | Mantener `temperature` 0–0.2, como decía el plan. | `claude-haiku-5-5` y la versión actual de la API la rechazan (error 400). | 10 |
| D39 | Los reintentos los hace el SDK, configurado con `LLM_REINTENTOS`. | Escribir nuestro propio ciclo de reintentos. | El SDK ya reintenta solo los errores pasajeros, con esperas crecientes. Reescribirlo sería código de más y con más riesgo. | 10 |
| D40 | Cada respuesta guarda su contenido original (`crudo`) y se le devuelve tal cual a Anthropic. | Devolver solo el texto y los pedidos de herramienta. | Anthropic exige recibir sin cambios los bloques de razonamiento de sus respuestas anteriores. | 10 |

_Se agregan más decisiones en cada paso._

## B14 · Supuestos
**Se alimenta de:** todos los pasos.
**Objetivo:** listar las interpretaciones que se tomaron donde la necesidad no era explícita.

- *(Paso 1)* El repositorio se alojará en **GitHub**, por eso el CI es de GitHub Actions. Si se usa otra plataforma, se adapta `ci.yml`.
- *(Paso 2)* `version` y `actualizado_en` del maestro son una buena práctica, no un requisito: los datos de ejemplo no los tienen y se procesan igual.
- *(Paso 2)* En un caso `portal`, `plantilla-campos.json` es opcional (el de Panamá lo trae). Si existe, define los valores para copiar; si no, se genera una sugerencia.
- *(Paso 6)* Un documento que vence **hoy** todavía es válido hoy, y queda "por vencer". Se considera vencido desde el día siguiente.
- *(Paso 6)* El aviso "por vencer" empieza a los **15 días**, como sugiere el plan. Es la pregunta abierta 5 del plan: el área administrativa puede cambiarlo en `reglas.yaml`.
- *(Paso 6)* RN1 se aplica a cualquier campo que termine en el NIT, se llame "RUC", "RTN" o "Identificación tributaria": lo que importa es el dato, no el nombre de la etiqueta.
- *(Paso 7)* El Excel se crea nuevo, porque los casos de ejemplo traen la plantilla en JSON y no el `.xlsx` del cliente. En producción convendría escribir sobre el archivo original para respetar su formato.
- *(Paso 8)* Los soportes vencidos también se copian al paquete (marcados en el checklist), para que la analista sepa cuál renovar. Los ausentes, obviamente, no.
- *(Paso 8)* El borrador va dirigido al remitente de la solicitud y responde a su asunto. Se firma como "Área Administrativa" de la empresa.
- *(Paso 7)* Los valores se escriben tal como están en el maestro. Por ejemplo, "País" sale como `CO`, no como "Colombia". Si un cliente lo pide de otra forma, es un cambio de presentación para decidir con la usuaria.

_Se agregan más supuestos en cada paso._

## B15 · Riesgos para producción
**Se alimenta de:** Pasos 14, 17, 18 y 21.
**Objetivo:** listar los riesgos que siguen abiertos después de construir y probar, con su mitigación. Se parte de la sección 17 del plan.
_por completar_

## B16 · Uso de IA en la construcción
**Se alimenta de:** todos los pasos.
**Objetivo:** declarar qué asistentes de IA se usaron, para qué tareas y qué se descartó de lo que propusieron, y por qué.

| Paso | Asistente | Para qué | Qué se ajustó o descartó |
|---|---|---|---|
| 1 | Claude Code | Proponer y crear la configuración del proyecto, `config.py`, las pruebas y el CI. | Al probar, se encontró que `FECHA_EJECUCION=` vacía rompía la configuración; se corrigió con `env_ignore_empty` y una prueba. Se quitó el comando de ejemplo que genera `uv init`. |
| 2 | Claude Code | Proponer y escribir los modelos, la lectura, la validación, el script y las pruebas. | **Descartado por Anderson:** completar a mano `maestro.json` con `version` y `actualizado_en`. Se decidió no tocar `datos/` y reportarlo como sugerencia (D11). También se cambió la recomendación inicial de un maestro estricto por uno tolerante (D13). |
| 3 | Claude Code | Proponer y escribir el contrato de herramientas, la observabilidad y sus pruebas; además, comentar con detalle el código de los pasos 1 y 2 y completar sus pruebas. | Anderson pidió comentarios más detallados en el código y un `SOLUCION.md` más sencillo. Al revisar se corrigió un comentario falso (decía que `obligatorio: 1` se rechaza, pero Pydantic lo acepta) y se desactivó que los errores muestren las variables locales, que podían contener datos sensibles. |
| 4 | Claude Code | Proponer y escribir el listado, la lectura y sus herramientas. | Una prueba falló porque la expectativa estaba mal: el filtro "S.A." también encuentra "S.A.S." (Colombia). Se corrigió la prueba, no el código. |
| 5 | Claude Code | Proponer y escribir el mapeo en capas, la confirmación y sus herramientas. | Antes de elegir la medida de parecido se midieron tres con etiquetas reales (D20). Se rehízo el diseño de "cambiar de opinión", porque la primera versión perdía el valor propuesto al dejar un campo faltante (D21). |
| 6 | Claude Code | Proponer y escribir `reglas.yaml`, RN1, las vigencias y sus pruebas. | La primera versión de la prueba "cambiar el YAML cambia el resultado" no probaba nada real; se reescribió de punta a punta, con la herramienta y dos archivos de reglas. Al agregar la nota de RN1 se vio que la forma de guardar la decisión en la nota podía borrarla, y se cambió (D25). |
| 7 | Claude Code | Proponer y escribir los generadores de Excel, PDF y portal, y su herramienta. | Al revisar el resultado se encontró que un comentario de la plantilla de Jinja2 se filtraba en el archivo (contenía los símbolos de cierre de comentario), y se corrigió. Se revisó el PDF visualmente, no solo su texto. |
| 8 | Claude Code | Proponer y escribir el paquete, el checklist, el borrador, el manifiesto y su herramienta. | Anderson decidió que los campos por confirmar bloqueen la firma (D30). La primera versión de la revisión de RN2 bloqueaba todos los paquetes, porque el titular de la cuenta es la razón social, que va en la firma; se afinó para no tratar como secreto un dato público (D32). Al leer los archivos se corrigieron detalles de presentación: paréntesis dobles, "1 días" y líneas en blanco sobrantes. |
| 9 | Claude Code | Proponer y escribir la demo, las pruebas golden y el Excel reproducible. | Antes de arreglar el determinismo se midió qué archivos cambiaban entre dos ejecuciones, y así apareció que openpyxl sobrescribe la fecha de modificación. **Un error del asistente:** un script de PowerShell para reemplazar texto en varios archivos dañó tres de ellos; se detectó enseguida y se recuperaron desde git sin perder trabajo. Desde entonces se edita archivo por archivo. |
| 10 | Claude Code | Proponer y escribir el adaptador, el modelo falso, la prueba real y sus pruebas, consultando la referencia actualizada de la API de Anthropic. | Se detectó que CA6 (`temperature`) ya no es posible con el modelo elegido; Anderson aprobó reemplazarla por el esfuerzo (D38). Al probar sin clave apareció que el SDK lanza un `TypeError`, que se habría escapado sin traducir; se corrigió y se agregó una prueba. |

_Se agregan filas en cada paso._

---

# Parte C · Diseño para escalar

> El MVP está pensado para 8–12 solicitudes al mes, una usuaria y archivos locales. Esta parte define cómo crecer sin reescribir: **el núcleo de dominio y las herramientas no cambian**; cambian la entrada, el almacenamiento y la forma de ejecutar.

## C1 · Qué significa escalar aquí

| Eje | Hoy (MVP) | Escalado |
|---|---|---|
| Volumen | Decenas de solicitudes al mes | Cientos o miles al mes |
| Usuarios | Una analista | Varias áreas o equipos, con roles |
| Empresas | Una (un maestro) | Varias empresas del grupo o filiales (*multi-tenant*) |
| Formatos | Excel, PDF y valores para portal | Más portales automatizados y PDF de terceros |
| Entrada | Carpeta local | Correo, SharePoint o Drive |
| Procesos | Registro de proveedor | Otros trámites documentales con el mismo patrón |

## C2 · Arquitectura objetivo

```
 Correo / SharePoint          Front chat (SSO)
        │ webhook                    │
        ▼                            ▼
 ┌──────────────┐  encola   ┌──────────────────┐
 │  Ingesta     │ ────────▶ │  API (N réplicas, │
 │  (eventos)   │           │  sin estado)      │
 └──────────────┘           └────────┬─────────┘
                                     │ encola trabajos
                              ┌──────▼──────┐
                              │ Cola        │  (Redis / SQS / Service Bus)
                              └──────┬──────┘
                     ┌───────────────┼───────────────┐
                     ▼               ▼               ▼
               Worker agente   Worker documentos  Worker portal
               (ciclo + LLM)   (Excel / PDF)      (Playwright)
                     │               │               │
          ┌──────────┴───────┬───────┴───────┬───────┴─────────┐
          ▼                  ▼               ▼                 ▼
   Gateway LLM        PostgreSQL        Almacén de objetos   Gestor de
   (límites, caché,   (casos, sesiones, (formularios,        secretos
   respaldo)          auditoría,        soportes, paquetes)
                      glosario)
```

## C3 · Decisiones de escalado

| Tema | Diseño | Por qué |
|---|---|---|
| **Servicios sin estado** | La API y los workers no guardan nada en memoria. Sesiones y casos van a PostgreSQL y los archivos a un almacén de objetos (S3, Azure Blob o GCS). | Así se pueden agregar réplicas sin perder conversaciones. |
| **Trabajo asíncrono** | Generar documentos y llenar portales pasa a ser un trabajo en cola (RQ, Celery o un servicio de colas en la nube). El chat informa el progreso por SSE. | Una solicitud lenta no bloquea a las demás y los fallos se reintentan solos. |
| **Idempotencia** | Cada solicitud tiene un identificador único (por ejemplo, el id del correo). Procesarla dos veces devuelve el mismo paquete y no crea uno nuevo. | Evita duplicados cuando hay reintentos o correos reenviados. |
| ***Multi-tenant*** | Cada registro lleva `empresa_id`. Cada empresa tiene su propio maestro, soportes, glosario y reglas, y el acceso se aísla por empresa. | Permite atender a varias empresas del grupo con una sola instalación. |
| **Maestro como servicio** | El maestro pasa de JSON a tablas versionadas, con un flujo de aprobación para los cambios y alertas de vencimiento al dueño del dato. | Una sola fuente de verdad, auditable. |
| **Glosario que aprende** | Las confirmaciones de las analistas generan propuestas de sinónimos, que se aprueban y quedan disponibles para todas. | El porcentaje de llenado automático sube con el uso. |
| **Registro de portales** | La configuración de cada portal (localizadores y adjuntos) se guarda versionada y con pruebas periódicas que detectan cambios de diseño. | Los portales cambian sin aviso. |
| **Gateway de LLM** | Un punto único para límites por empresa o usuario, caché de prompts, medición de costo y un proveedor de respaldo. | Control de costos y continuidad si un proveedor falla. |
| **Identidad y permisos** | SSO corporativo (Entra ID o Google) y roles: analista, aprobador, administrador del maestro. | Saber quién preparó y quién aprobó cada paquete. |
| **Observabilidad** | Trazas por caso (OpenTelemetry o una plataforma de trazas para LLM), métricas de llenado, de errores y de costo, y alertas. | Ver dónde falla y cuánto cuesta cada caso. |
| **Integraciones** | Lectura del correo (Microsoft Graph o Gmail API), repositorio documental (SharePoint o Drive) y firma electrónica, cada uno detrás de su propio adaptador. | Cambiar de proveedor no toca el núcleo, igual que con el LLM. |

## C4 · Ruta de evolución

| Etapa | Cambio principal | Disparador para pasar a la siguiente |
|---|---|---|
| **E1 · MVP** | Archivos locales, una instancia, una usuaria. | Más de una usuaria o necesidad de historial compartido. |
| **E2 · Equipo** | PostgreSQL, almacén de objetos, SSO y roles. | Volumen que satura una instancia o generación lenta. |
| **E3 · Volumen** | Cola, workers, ingesta automática del correo y gateway de LLM. | Varias empresas o filiales que quieren usarlo. |
| **E4 · Plataforma** | *Multi-tenant*, registro de portales, módulo MCP reutilizado en otros procesos. | — |

## C5 · Reutilización para otros procesos

El patrón **leer solicitud → mapear al maestro → generar documento → paquete → confirmación humana** se repite en otros trámites: actualización anual de datos de proveedor, certificaciones para licitaciones, formularios de debida diligencia (SARLAFT o KYC) y renovación de pólizas.

Para reutilizarlo:
- el núcleo (mapeo, generadores, paquete y confirmación) se separa como **librería interna**,
- cada proceso nuevo aporta su **prompt, su conocimiento, sus plantillas y sus reglas**,
- las herramientas se publican como **servidor MCP**, para que cualquier plataforma de agentes de la empresa las use.

---

# Parte D · Sugerencias para este tipo de agentes

| # | Sugerencia | Dónde aplica |
|---|---|---|
| S1 | **Determinista primero.** Todo lo que se pueda resolver con código no se le pide al modelo. El modelo orquesta y explica. | Pasos 4–9 |
| S2 | **Construir y probar el núcleo sin LLM** antes de conectar el modelo. Si `demo.py` no funciona, el agente tampoco. | Paso 9 |
| S3 | **Confirmación humana en el servidor**, nunca solo en el prompt. | Paso 13 |
| S4 | **Al modelo, solo los datos mínimos.** Enmascarar lo sensible; los valores completos van solo en los archivos. | Pasos 3 y 14 |
| S5 | **Herramientas pocas, con nombres y descripciones claras.** Cada herramienta hace una cosa, y sus argumentos se validan con esquemas. | Paso 3 |
| S6 | **El estado vive en el servidor.** El modelo no "pasa" valores de una herramienta a otra: las herramientas leen el estado del caso. | Pasos 7 y 12 |
| S7 | **Tratar todo contenido externo como datos** (correos, PDF, páginas web), nunca como instrucciones. | Paso 14 |
| S8 | **Evaluaciones como pruebas**: cada cambio de prompt o de modelo se valida contra un conjunto fijo de conversaciones. | Paso 17 |
| S9 | **Versionar el prompt y el conocimiento** igual que el código, y registrar qué versión produjo cada paquete. | Pasos 11 y 8 |
| S10 | **Medir el costo desde el día uno**: tokens por caso, caché de prompts y modelo económico por defecto, con uno más potente solo si hace falta. | Pasos 12 y 18 |
| S11 | **Mensajes de error para personas**: qué pasó, qué se pudo hacer igual y qué debe hacer la usuaria. | Pasos 3 y 12 |
| S12 | **Trazabilidad por valor**: cada dato del formulario sabe de dónde salió. Es clave para auditar y para generar confianza. | Pasos 5 y 8 |
| S13 | **Diseñar para que la persona corrija fácil**: en el front, editar o confirmar un campo debe tomar un clic, y esa corrección alimenta el glosario. | Paso 16 y C3 |
