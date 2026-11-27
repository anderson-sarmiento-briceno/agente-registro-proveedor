# Agente · Registro como Proveedor

Un agente de IA que prepara el **registro de una empresa como proveedor** ante sus clientes.
El cliente envía su formulario (Excel, PDF o un portal web) y la lista de documentos que
exige. El agente lo llena con los datos del repositorio maestro de la empresa, revisa los
soportes (vigentes, por vencer, vencidos o ausentes) y arma el paquete para firma. Además,
dice con claridad qué falta.

**Demo en vivo:** <https://agente-registro-proveedor-yu72.onrender.com>.
Usa datos de una empresa ficticia («Empresa Ejemplo S.A.S.») y cuatro casos de ejemplo:
Colombia, Ecuador, Honduras y Panamá. La primera visita puede tardar cerca de un minuto,
porque el servidor gratuito se apaga cuando nadie lo usa.

## Cómo funciona, en una frase

El modelo de lenguaje **decide qué herramienta usar y conversa**. Los valores, las reglas
y las validaciones las hace **código**: ningún valor se inventa, lo sensible sale
enmascarado y nada se confirma ni se envía sin que una persona pulse **Aprobar**.

Para un caso completo, el modelo pide las herramientas en este orden:

```
proveedor_listar_casos → proveedor_leer_solicitud → proveedor_mapear_campos
  → proveedor_generar_formulario → proveedor_armar_paquete
  (con aprobación: proveedor_confirmar_campo, proveedor_registrar_envio)
```

## Probarlo en su computador

Requisitos: [Git](https://git-scm.com/downloads) y
[uv](https://docs.astral.sh/uv/getting-started/installation/). uv instala Python solo.

```
git clone https://github.com/anderson-sarmiento-briceno/agente-registro-proveedor.git
cd agente-registro-proveedor
uv sync
uv run python scripts/demo.py --llamadas     # los 4 casos, SIN modelo y sin clave
```

Para el chat con el modelo, copie `.env.example` como `.env` y ponga su clave de Anthropic
en `ANTHROPIC_API_KEY`. Luego:

```
uv run uvicorn registro_proveedor.api.app:app    # http://127.0.0.1:8000
docker compose up --build                        # o lo mismo en un contenedor
```

## Usarlo desde Claude Desktop o Claude Code (MCP)

Las herramientas también se publican como **servidor MCP**, para usarlas desde otras
plataformas de agentes, sin la página ni la clave de Anthropic. Hay dos formas:

- **Sin instalar nada:** en Claude, *Configuración → Plugins → **Agregar ⌄** → Agregar
  conector personalizado*, con la URL `https://agente-registro-proveedor-yu72.onrender.com/mcp`
  y la autenticación en «Sin inicio de sesión».
- **En su computador:** descargando el proyecto en ZIP (sin Git) e instalando uv.

La guía paso a paso de las dos está en **[modulo/LEEME.md](modulo/LEEME.md)**. En esa
carpeta también están las instrucciones del agente (`agent.md`) y el conocimiento del
proceso (`SKILL.md`).

## Documentación

| Archivo | Qué tiene |
|---|---|
| [PLAN-agente-registro-proveedor.md](PLAN-agente-registro-proveedor.md) | El problema, el alcance, las reglas de negocio, la arquitectura y los riesgos |
| [SOLUCION.md](SOLUCION.md) | Cómo se construyó paso a paso, las decisiones tomadas, las pruebas, las evaluaciones y el diseño para escalar |
| [modulo/LEEME.md](modulo/LEEME.md) | Cómo instalar el servidor MCP |

## Calidad

```
uv run pytest                                   # más de 600 pruebas, sin red
uv run ruff check . ; uv run mypy src           # estilo y tipos estrictos
```

El CI de GitHub Actions corre todo esto en cada cambio. Las evaluaciones con el modelo
real (`scripts/evaluar.py`) se corren a mano, porque gastan dinero, y sus reportes quedan
en `evals/reportes/`.

Hecho con Python 3.13, FastAPI, Pydantic, el SDK de Anthropic (`claude-haiku-5-5`) y el
SDK de MCP.
