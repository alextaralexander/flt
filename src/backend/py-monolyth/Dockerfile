# syntax=docker/dockerfile:1
# py-main-lib — path-зависимость uv (`../py-main-lib` в pyproject.toml); в образ она попадает
# из build-context-а и кладётся в /py-main-lib, чтобы относительный путь из uv.lock совпал:
#   docker build --build-context py-main-lib=../py-main-lib .
# В docker-compose контекст задан в deploy/docker-compose/docker-compose.yml (additional_contexts).

# --- Стадия 1: сборка окружения из uv.lock ----------------------------------
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Сначала только манифесты и py-main-lib: слой зависимостей кэшируется между сборками.
# WORKDIR /app, поэтому `../py-main-lib` из uv.lock — это /py-main-lib.
COPY pyproject.toml uv.lock ./
COPY --from=py-main-lib . /py-main-lib
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

COPY . .

# --- Стадия 2: рантайм (без uv, без кэшей, non-root) -------------------------
FROM python:3.14-slim

RUN groupadd --gid 1000 app && useradd --uid 1000 --gid app --no-create-home app

WORKDIR /app
COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER app

# В многорепличном деплое выключай миграции при старте (MIGRATE_ON_START=false)
# и выполняй `alembic upgrade head` отдельным job/init-container-ом.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"FAST_API_PORT\", \"8000\")}/v1/health')"]

CMD ["python", "uvi_run.py"]
