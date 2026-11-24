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
| 3 | Base de herramientas y observabilidad | F0 | ⬜ |
| 4 | Listado y lectura de solicitudes | F1 | ⬜ |
| 5 | Mapeo de campos y su confirmación | F1 | ⬜ |
| 6 | Reglas de negocio configurables | F1 | ⬜ |
| 7 | Generación de formularios | F1 | ⬜ |
| 8 | Paquete para firma | F1 | ⬜ |
| 9 | Demostración sin modelo y pruebas *golden* | F1 | ⬜ |
| 10 | Adaptador del modelo de lenguaje | F2 | ⬜ |
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
- `pyproject.toml` con todas las dependencias del stack, fijadas en `uv.lock`, y la configuración de ruff, mypy (`strict` + plugin de Pydantic) y pytest. Python ≥ 3.12 (local: 3.13).
- `src/registro_proveedor/config.py`: la clase `Configuracion` (pydantic-settings) lee `.env`. La API key es opcional y es `SecretStr`, así que nunca se imprime. La fecha de ejecución es inyectable (RN7).
- `.env.example` con `ANTHROPIC_API_KEY`, `LLM_MODELO`, `FECHA_EJECUCION` y `NIVEL_LOG`, sin valores secretos. Las variables vacías se tratan como ausentes (`env_ignore_empty`).
- `tests/test_entorno.py`: 5 pruebas (importación, carga sin clave, clave oculta, fecha inyectada, `.env.example` copiado tal cual).
- `.github/workflows/ci.yml`: `uv sync --locked` → ruff check → ruff format → mypy → pytest. En local todo pasa; en GitHub se verá en verde con el primer *push*, cuando exista el remoto.

### Paso 2 · Modelos de datos y validación de insumos
**Objetivo:** describir con Pydantic la solicitud, las plantillas, el maestro, los soportes y el glosario, y detectar los datos rotos antes de procesarlos, sin modificar nunca `datos/`.
**Hecho cuando:** `validar_datos.py` revisa todos los insumos, incluidas las rutas del glosario contra el maestro, y reporta en lenguaje claro los **errores** (dato roto: el CI falla) separados de las **sugerencias** para el dueño del dato (dato mejorable: el CI no falla). Con los datos de ejemplo: 0 errores y la sugerencia de agregar `version` y `actualizado_en` al maestro.
**Estado:** ✅
**Avance:**
- `dominio/modelos.py`: `Solicitud`, `CeldaPlantilla`, `CampoPlantilla`, `Soporte`, `Maestro` (con submodelos) y `Glosario`, más los enums `Pais`, `Formato` y `TipoSoporte`. Los archivos del caso son estrictos y el maestro es tolerante (solo `razon_social` y `nit` son obligatorios).
- `dominio/lectura.py`: una función `cargar_*` por archivo. Rechaza el JSON mal formado, las claves repetidas y los nombres de caso peligrosos (`../`), y traduce los errores de Pydantic a español con su ubicación (`elemento 3 > «celda_valor»`).
- `dominio/validacion.py`: revisiones que cruzan archivos (id y carpeta, plantilla según el formato, celdas repetidas, rutas del glosario contra el maestro, archivos de soporte). El reporte separa errores y sugerencias, y un caso roto no impide revisar los demás.
- `scripts/validar_datos.py`: imprime el reporte y termina con 1 solo si hay errores. Se agregó al CI.
- 46 pruebas nuevas (51 en total) que rompen una copia temporal de `datos/`. Una de ellas verifica que validar no modifica los datos reales. Resultado real: **0 errores, 1 sugerencia**.

### Paso 3 · Base de herramientas y observabilidad
**Objetivo:** crear el contrato común de las herramientas (`Resultado`, decorador `@herramienta` y registro), los logs estructurados y el enmascaramiento de datos sensibles.
**Hecho cuando:** una herramienta de ejemplo valida sus argumentos, nunca lanza excepciones, escribe en `log.jsonl` y enmascara los valores sensibles.
**Estado:** ⬜
**Avance:** _por completar_

## Fase F1 · Núcleo determinista

### Paso 4 · Listado y lectura de solicitudes
**Objetivo:** `proveedor_listar_casos` muestra los casos disponibles (cliente, país y formato), con un filtro opcional, para que el agente identifique "el de Ecuador". `proveedor_leer_solicitud` devuelve el país, el cliente, el formato, los campos y los soportes exigidos de un caso.
**Hecho cuando:** el listado filtra por cliente o país, la lectura responde correctamente en los 4 casos de referencia y ambas devuelven un error claro ante un caso inexistente o una plantilla corrupta.
**Estado:** ⬜
**Avance:** _por completar_

### Paso 5 · Mapeo de campos y su confirmación
**Objetivo:** `proveedor_mapear_campos` clasifica cada campo en `lleno`, `faltante` o `requiere_confirmacion`, en capas (exacto → normalizado → similitud), deja registrados el origen y el método, y guarda el mapeo en `out/<caso>/mapeo.json`. `proveedor_confirmar_campo` resuelve un campo en `requiere_confirmacion` (aceptar o dejar faltante) y registra la decisión en ese mapeo.
**Hecho cuando:** las pruebas unitarias cubren cada capa, ninguna prueba produce un valor que no exista en el maestro y una confirmación cambia el estado del campo sin tocar los demás. *(El bloqueo que obliga a aprobarla en el front se conecta en el Paso 13.)*
**Estado:** ⬜
**Avance:** _por completar_

### Paso 6 · Reglas de negocio configurables
**Objetivo:** llevar a `config/reglas.yaml` las reglas de identificador por país, de datos bancarios, de vigencias y "por vencer", y de fecha de ejecución inyectable (RN1–RN8).
**Hecho cuando:** cada regla tiene su prueba, y cambiar un umbral en el YAML cambia el resultado sin tocar el código.
**Estado:** ⬜
**Avance:** _por completar_

### Paso 7 · Generación de formularios
**Objetivo:** `proveedor_generar_formulario` produce el Excel en las celdas exactas, el PDF con las etiquetas en orden (o el AcroForm rellenado) y `valores-portal.md` para los portales.
**Hecho cuando:** los tres formatos se generan desde el mapeo guardado (no desde el modelo) y los campos faltantes quedan vacíos y resaltados.
**Estado:** ⬜
**Avance:** _por completar_

### Paso 8 · Paquete para firma
**Objetivo:** `proveedor_armar_paquete` crea la carpeta con el formulario, los soportes, `checklist.md`, `borrador-correo.md` y `manifiesto.json`, y calcula `listo_para_firma`.
**Hecho cuando:** un soporte vencido o ausente bloquea el estado y el borrador nunca contiene datos bancarios.
**Estado:** ⬜
**Avance:** _por completar_

### Paso 9 · Demostración sin modelo y pruebas *golden*
**Objetivo:** `scripts/demo.py` procesa todos los casos llamando directamente a las herramientas, y las pruebas *golden* fijan el resultado esperado de cada caso.
**Hecho cuando:** dos ejecuciones seguidas con la misma fecha dan exactamente el mismo resultado, sin ninguna clave de LLM.
**Estado:** ⬜
**Avance:** _por completar_

## Fase F2 · Agente y chat

### Paso 10 · Adaptador del modelo de lenguaje
**Objetivo:** definir la interfaz `enviar(mensajes, herramientas) → respuesta` (un `Protocol`) y una implementación para el proveedor elegido, con timeout y reintentos.
**Hecho cuando:** existe un adaptador falso para las pruebas y cambiar de proveedor no toca el ciclo del agente.
**Estado:** ⬜
**Avance:** _por completar_

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

**Base del proyecto (Paso 1):**
- El código vive en `src/registro_proveedor/` (estructura *src*): las pruebas importan el paquete instalado, no archivos sueltos.
- `config.py` es el **único punto de lectura de configuración**. Las demás capas reciben un objeto `Configuracion` y nunca leen `os.environ`. `RAIZ_PROYECTO` es la base para resolver `datos/` y `out/`.
- Las carpetas de cada capa (`dominio/`, `herramientas/`, `agente/`, `api/`) se crean en el paso que las necesita.

**Dominio: modelos, lectura y validación (Paso 2):**

| Módulo | Responsabilidad |
|---|---|
| `dominio/modelos.py` | La forma de cada insumo (Pydantic). No lee archivos. |
| `dominio/lectura.py` | Lee un JSON, lo convierte en su modelo y, si falla, lanza `ErrorDeDatos` con los problemas en español. Concentra los nombres de los archivos y la protección de rutas. |
| `dominio/validacion.py` | Revisa todos los insumos juntos y devuelve un `Reporte` de errores y sugerencias. |

Dentro del dominio, un dato roto **sí lanza** `ErrorDeDatos`. La capa de herramientas (Paso 3) lo convertirá en `Resultado(ok=False, error=...)`, de modo que el agente nunca reciba una excepción.

_El resto se completa en los pasos 3, 10, 15 y 16._

## B3 · Núcleo determinista: lectura, mapeo, reglas y generación
**Se alimenta de:** Pasos 4, 5, 6, 7 y 8.
**Objetivo:** explicar cómo se lee una solicitud, cómo funciona el mapeo en capas y sus niveles de confianza, dónde están configuradas las reglas de negocio y cómo se generan el formulario y el paquete.
_por completar_

## B4 · Calidad y pruebas
**Se alimenta de:** Pasos 9 y 17.
**Objetivo:** describir la estrategia de pruebas (unitarias, *golden*, `demo.py` y evaluaciones del agente), qué cubre cada nivel, cómo corren en el CI y los resultados obtenidos.
_por completar_

## B5 · Elección del modelo y costo
**Se alimenta de:** Pasos 10 y 18.
**Objetivo:** indicar el proveedor y el modelo, por qué se eligieron, cómo se cambia de proveedor gracias al adaptador y el costo real medido por caso procesado.
_por completar_

## B6 · Ciclo del agente y confirmación humana
**Se alimenta de:** Pasos 11, 12 y 13.
**Objetivo:** explicar el bucle mensaje → modelo → herramientas, los topes de iteraciones y de tokens, el manejo de errores, la separación entre prompt y conocimiento, y la confirmación humana controlada por el servidor.
_por completar_

## B7 · Seguridad y guardarraíles
**Se alimenta de:** Pasos 3, 14 y 18.
**Objetivo:** documentar el manejo de secretos, el enmascaramiento de datos sensibles, los datos mínimos que se envían al modelo, la defensa contra la inyección de prompts, la verificación de valores, la protección del acceso y los topes de costo.
_por completar_

## B8 · Diseño para portales web
**Se alimenta de:** Paso 7 y la sección 14 del plan.
**Objetivo:** resumir lo implementado (valores para copiar y adjuntos) y el diseño del navegador asistido: credenciales, límites y reparto de tareas entre el agente y la persona.
_por completar_

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

_`demo.py`, el despliegue y la URL se completan en los pasos 9 y 19._

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
| HU-1 Leer la solicitud | 4 | ⬜ | |
| HU-2 Mapear campos | 5, 6 | ⬜ | |
| HU-3 Generar formulario | 7 | ⬜ | |
| HU-4 Paquete para firma | 8 | ⬜ | |
| HU-5 Envío con confirmación | 13 | ⬜ | |
| HU-6 Manejo de errores | 3, 12 | ⬜ | |
| HU-7 Trazabilidad | 3, 8 | ⬜ | |

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

_Se agregan más decisiones en cada paso._

## B14 · Supuestos
**Se alimenta de:** todos los pasos.
**Objetivo:** listar las interpretaciones que se tomaron donde la necesidad no era explícita.

- *(Paso 1)* El repositorio se alojará en **GitHub**, por eso el CI es de GitHub Actions. Si se usa otra plataforma, se adapta `ci.yml`.
- *(Paso 2)* `version` y `actualizado_en` del maestro son una buena práctica, no un requisito: los datos de ejemplo no los tienen y se procesan igual.
- *(Paso 2)* En un caso `portal`, `plantilla-campos.json` es opcional (el de Panamá lo trae). Si existe, define los valores para copiar; si no, se genera una sugerencia.

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
