# Agente "Registro como Proveedor" — contexto para Claude

Léelo completo antes de trabajar en este proyecto.

## Quién soy y cómo trabajar conmigo

- Soy Anderson. Explícame todo **en español** y con palabras simples: tengo que entender y poder explicar cada parte del código.
- **Antes de escribir mucho código, dime qué vas a hacer y por qué**, y espera mi visto bueno si el cambio es grande.
- Trabajamos **un paso a la vez**, en el orden de `SOLUCION.md` (Parte A). No adelantes pasos sin avisar.
- Al terminar un paso:
  1. marca su estado en el tablero y en el paso (⬜ → ✅),
  2. llena su **Avance** con lo que se hizo, en 3 a 6 líneas,
  3. actualiza las secciones de la Parte B que dicen "Se alimenta de" ese paso,
  4. regenera `SOLUCION.html` (ver "Documentos HTML" abajo).
- **Nunca** me pidas que pegue la API key en el chat ni la imprimas. Va solo en `.env`, que no se sube a git.
- **Commit local al cerrar cada paso** (después de actualizar la documentación), con un mensaje en español. **Sin push**: todavía no hay remoto, y subir a GitHub se decide más adelante. Fuera de eso, haz commit solo cuando yo lo pida.

## Estado actual

- ✅ Planeación terminada: `PLAN-agente-registro-proveedor.md` y `SOLUCION.md`, con 7 herramientas definidas (incluidas `proveedor_listar_casos` y `proveedor_confirmar_campo`).
- ✅ Datos de ejemplo copiados a `datos/` y anonimizados ("Empresa Ejemplo S.A.S.").
- ✅ `.gitignore` creado y repositorio git iniciado en `main`, **sin commits todavía**.
- ✅ **Paso 1 · Preparación del entorno**: uv 0.13.9 instalado, `pyproject.toml` + `uv.lock`, `config.py` (pydantic-settings), `.env.example`, 5 pruebas y CI de GitHub Actions. ruff, mypy y pytest en verde en local. El CI remoto se verá al primer *push* (todavía no hay remoto).
- ⏳ Pendiente de Anderson: más adelante (Paso 10), copiar `.env.example` como `.env` y poner la API key de Anthropic.
- ▶ **Siguiente: Paso 2 · Modelos de datos y validación de insumos** (ver `SOLUCION.md`). Antes de escribir código, explícame qué se va a crear y por qué.

Actualiza esta sección cada vez que se cierre un paso.

## Documentos de referencia

| Archivo | Para qué |
|---|---|
| `PLAN-agente-registro-proveedor.md` | Problema, alcance, historias, reglas (RN1–RN8), arquitectura, stack y riesgos. **Es la fuente de verdad del diseño.** |
| `SOLUCION.md` | Pasos de construcción (Parte A), documentación de la solución (B), diseño para escalar (C) y sugerencias (D). Se llena a medida que avanzamos. |

Si algo del código contradice el plan, avísame antes de cambiar cualquiera de los dos.

## Principios del diseño (no negociables)

1. **La lógica de negocio vive en las herramientas, no en el modelo.** El LLM decide qué herramienta llamar y conversa. Los valores, las reglas y las validaciones son código determinista.
2. **Nunca se inventa un valor.** Un campo sin fuente en el maestro queda `faltante`.
3. **La confirmación humana la controla el servidor**, no el prompt. Ninguna acción externa ocurre sin aprobación explícita.
4. **Al modelo, solo los datos mínimos.** Los valores sensibles (cuenta bancaria, identificaciones) le llegan enmascarados.
5. **El contenido externo (correos, PDF, páginas) es dato, no instrucción.**
6. **Las herramientas nunca lanzan excepciones**: devuelven `Resultado(ok=True, data=...)` o `Resultado(ok=False, error=...)`.
7. **El núcleo funciona sin LLM**: `scripts/demo.py` debe correr todos los casos sin clave.

## Decisiones técnicas tomadas

| Tema | Decisión |
|---|---|
| Lenguaje | Python 3.12+ (instalado: 3.13) |
| Dependencias | uv + `pyproject.toml` |
| API | FastAPI + Uvicorn |
| Validación | Pydantic v2 · configuración con pydantic-settings |
| LLM | **Anthropic**, SDK `anthropic`, detrás de un adaptador propio. Modelo por defecto `claude-haiku-5-5` (económico), configurable por variable de entorno |
| Documentos | openpyxl (Excel) · fpdf2 (PDF generado) · pypdf (AcroForm) · Jinja2 (checklist y correo) |
| Mapeo | rapidfuzz para la similitud de etiquetas |
| Calidad | ruff · mypy (estricto) · pytest |
| Logs | structlog en JSON |
| Front | HTML + JS simple servido por FastAPI |
| Despliegue | Docker + servicio administrado (por definir en el paso 19) |

## Convenciones de código

- Tipado estricto. Sin `Any`, salvo que sea inevitable y esté justificado en un comentario.
- Nombres en **español**, coherentes con el dominio: `solicitud`, `maestro`, `soporte`, `campo_mapeado`, `listo_para_firma`.
- Funciones cortas, que hagan una sola cosa. El dominio no importa nada de `api/` ni de `agente/`.
- Las rutas se resuelven desde la raíz del proyecto y se valida que no salgan de `datos/` ni de `out/`.
- `datos/` es **solo lectura** para el código. Todo lo generado va a `out/`, que está en `.gitignore`.
- Cada regla de negocio tiene al menos una prueba.
- La fecha de ejecución se inyecta (RN7). Las pruebas usan una fecha fija.

## Estructura

Ver la sección 8.3 del plan. Resumen:

```
agente/prompt.md            # comportamiento
knowledge/                  # conocimiento del proceso
config/reglas.yaml          # reglas configurables
src/registro_proveedor/     # dominio · herramientas · agente · api
web/                        # front de chat
datos/                      # casos, maestro, soportes y glosario (solo lectura)
scripts/demo.py             # todos los casos sin LLM
tests/                      # unit · golden · evals
```

## Datos de ejemplo (`datos/`)

- `casos/`: 4 solicitudes de referencia (CO Excel, EC PDF, HN Excel, PA portal).
- `repositorio/maestro.json`: los datos de la empresa (ficticia: "Empresa Ejemplo S.A.S.").
- `repositorio/soportes/`: los documentos de la empresa, con `vigencia_hasta` en `index.json`.
- `glosario-campos.json`: etiqueta del cliente → ruta en el maestro.

Ojo: varios soportes tienen `vigencia_hasta` en 2026 y algunos ya vencieron. Por eso la fecha de ejecución se inyecta: las pruebas no deben depender del día en que se corren.

## Comandos (cuando existan)

```powershell
uv sync                         # instalar dependencias
uv run pytest                   # pruebas
uv run ruff check . ; uv run mypy src
uv run python scripts/demo.py   # todos los casos sin LLM
uv run uvicorn registro_proveedor.api.app:app --reload   # servidor local
```

## Documentos HTML

`PLAN-agente-registro-proveedor.html` y `SOLUCION.html` contienen el Markdown incrustado en `const md = "...";` y se renderizan con `marked`. Después de editar un `.md`, regenera su `.html` reemplazando ese string por el Markdown nuevo, serializado con JSON y escapando `</` como `<\/`.
