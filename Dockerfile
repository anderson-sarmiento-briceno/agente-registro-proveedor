# Imagen del agente "Registro como Proveedor" (Paso 19).
#
# Qué hace, en orden:
#   1. Parte de Python 3.13 "slim" (liviano) y trae uv, la misma versión del proyecto.
#   2. Instala las dependencias EXACTAS de uv.lock, sin las de desarrollo. Se hace antes
#      de copiar el código: así, si solo cambia el código, Docker reutiliza esta capa y
#      la imagen se reconstruye en segundos.
#   3. Copia solo lo que el servidor necesita (ver .dockerignore: nunca .env ni out/).
#   4. Corre con un usuario SIN permisos de administrador.
#
# La clave de Anthropic NO está en la imagen: se pasa al arrancar como variable de
# entorno (docker compose la lee de .env; en Render se escribe en su panel, como secreto).

FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 2. Dependencias (capa que casi nunca cambia).
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# 3. El código y lo que lee en tiempo de ejecución. `datos/` son los datos de ejemplo
#    de la empresa ficticia; el código los trata como solo lectura.
COPY src/ src/
RUN uv sync --locked --no-dev
COPY agente/ agente/
COPY knowledge/ knowledge/
COPY config/ config/
COPY datos/ datos/
COPY web/ web/

# 4. Un usuario sin privilegios, dueño solo de out/ (lo único que el servidor escribe).
RUN useradd --create-home --uid 1000 agente \
    && mkdir -p /app/out \
    && chown agente /app/out
USER agente

# Render indica el puerto en la variable PORT; en local se usa 8000.
ENV PORT=8000
EXPOSE 8000

# ¿Está vivo? Docker llama a /api/health cada 30 s (con Python: la imagen no trae curl).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"

# Un solo proceso: las conversaciones viven en la memoria de ESTE proceso.
# --proxy-headers: detrás del proxy de Render, leer la IP real del visitante (para los
# topes por visitante del Paso 18).
CMD ["sh", "-c", "exec uvicorn registro_proveedor.api.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips '*'"]
