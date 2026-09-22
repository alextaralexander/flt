## ---------------------------------------------------------------------------
## python-boilerplate — единая точка входа для разработки и агентов.
## Запусти `make help`, чтобы увидеть все цели.
## ---------------------------------------------------------------------------

# Запускаем инструменты в окружении uv. Если uv недоступен — переопредели: make RUN= ...
RUN ?= uv run
COMPOSE_FILE ?= ../../../deploy/docker-compose/docker-compose.yml
# Инфраструктура для запуска сервиса на хосте (сам сервис в compose — сервис `backend`).
COMPOSE_INFRA ?= postgres redis kafka
# Локальный путь до py-main-lib (private registry недоступен — ставим из соседнего клона).
PY_MAIN_LIB ?= ../py-main-lib

.DEFAULT_GOAL := help
.PHONY: help install dev run test test-cov test-docker format format-check lint lint-fix typecheck \
        security secrets-scan check migrate makemigration asyncapi \
        scaffold-entity scaffold-subscriber lock pre-commit \
        compose-up compose-down docker-build clean

help: ## Показать список доступных команд
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# --- Окружение и зависимости (G8: uv) --------------------------------------

install: ## Установить зависимости из uv.lock (uv sync + py-main-lib)
	uv sync --all-groups
	@if [ -d "$(PY_MAIN_LIB)" ]; then \
		uv pip install --no-deps "$(PY_MAIN_LIB)"; \
	else \
		echo "py-main-lib не найден в $(PY_MAIN_LIB) — установи из private registry (см. CLAUDE.md)"; \
	fi

lock: ## Пересобрать uv.lock из pyproject.toml
	uv lock

# --- Запуск -----------------------------------------------------------------

dev: ## Запустить dev-сервер с автоперезагрузкой
	$(RUN) uvicorn app.main:app --reload --host $${FAST_API_HOST:-0.0.0.0} --port $${FAST_API_PORT:-8000}

run: ## Запустить приложение (prod-режим, как в Docker)
	$(RUN) python uvi_run.py

# --- Качество кода (ruff = формат + импорты + линт) --------------------------

format: ## Отформатировать код (ruff format + сортировка импортов)
	$(RUN) ruff check --select I --fix .
	$(RUN) ruff format .

format-check: ## Проверить форматирование без изменений
	$(RUN) ruff format --check .

lint: ## Линт (ruff check)
	$(RUN) ruff check .

lint-fix: ## Линт с автоисправлениями
	$(RUN) ruff check --fix .

typecheck: ## Проверка типов (mypy strict)
	$(RUN) mypy app cli configs

# --- Безопасность (G6) ------------------------------------------------------

security: ## Security-анализ: bandit + detect-secrets
	$(RUN) bandit -c pyproject.toml -r app cli
	$(RUN) detect-secrets-hook --baseline .secrets.baseline $$(git ls-files)

secrets-scan: ## Пересобрать .secrets.baseline (после ревью находок)
	$(RUN) detect-secrets scan --baseline .secrets.baseline

# --- Тесты ------------------------------------------------------------------

test: ## Прогнать тесты
	$(RUN) pytest

test-cov: ## Тесты с отчётом покрытия (порог — fail_under в pyproject.toml)
	$(RUN) pytest --cov=app --cov-report=term-missing

TEST_PG_CONTAINER ?= python-boilerplate-test-pg
TEST_PG_PORT ?= 54329

test-docker: ## Тесты в одноразовом Postgres (docker run), без локальной инфраструктуры
	@docker run -d --rm --name $(TEST_PG_CONTAINER) \
		-e POSTGRES_USER=ms_py_test -e POSTGRES_PASSWORD=ms_py_test -e POSTGRES_DB=flt \
		-p $(TEST_PG_PORT):5432 postgres:16-alpine >/dev/null
	@until docker exec $(TEST_PG_CONTAINER) pg_isready -U ms_py_test -d flt >/dev/null 2>&1; do sleep 0.5; done
	@docker exec $(TEST_PG_CONTAINER) psql -U ms_py_test -d flt \
		-c 'CREATE SCHEMA IF NOT EXISTS "ms_py_test"' >/dev/null
	@PG_PORT=$(TEST_PG_PORT) $(RUN) pytest; STATUS=$$?; \
		docker stop $(TEST_PG_CONTAINER) >/dev/null; \
		exit $$STATUS

# --- Полная проверка (Definition of Done) ----------------------------------

# format мутирующий: агенту/разработчику дешевле автоформат, чем цикл «отказ → make format → повтор».
check: format lint typecheck security test ## Полная проверка перед коммитом (DoD)

pre-commit: ## Прогнать pre-commit на всех файлах
	$(RUN) pre-commit run --all-files

# --- База данных ------------------------------------------------------------

migrate: ## Применить миграции Alembic (upgrade head)
	$(RUN) alembic upgrade head

makemigration: ## Создать ревизию: make makemigration name="add_x"
	@test -n "$(name)" || (echo "Укажи name=...: make makemigration name=\"add_x\"" && exit 1)
	$(RUN) alembic revision --autogenerate -m "$(name)"

# --- Скаффолдинг (G10) ------------------------------------------------------

scaffold-entity: ## Создать REST-сущность: make scaffold-entity name=Order
	@test -n "$(name)" || (echo "Укажи name=...: make scaffold-entity name=Order" && exit 1)
	$(RUN) python -m cli add-entity $(name)

scaffold-subscriber: ## Создать Kafka-сабскрайбер: make scaffold-subscriber topic=ORDER_CREATED value="svc.order.created.01"
	@test -n "$(topic)" || (echo "Укажи topic=... и value=...: make scaffold-subscriber topic=ORDER_CREATED value=\"svc.order.created.01\"" && exit 1)
	@test -n "$(value)" || (echo "Укажи value=...: make scaffold-subscriber topic=ORDER_CREATED value=\"svc.order.created.01\"" && exit 1)
	$(RUN) python -m cli add-subscriber $(topic) "$(value)"

# --- AsyncAPI / инфраструктура ---------------------------------------------

asyncapi: ## Показать, где доступна AsyncAPI-документация (нужен запущенный сервер)
	@echo "AsyncAPI Kafka: http://localhost:$${FAST_API_PORT:-8000}/asyncapi/kafka"
	@echo "Запусти сервер 'make dev' и открой ссылки или сделай curl."

compose-up: ## Поднять локальную инфраструктуру (PostgreSQL, Redis, Kafka) из deploy/docker-compose
	docker compose -f $(COMPOSE_FILE) up -d --wait $(COMPOSE_INFRA)

compose-down: ## Остановить локальную инфраструктуру
	docker compose -f $(COMPOSE_FILE) down

docker-build: ## Собрать Docker-образ сервиса (py-main-lib из локального клона)
	docker build --build-context py-main-lib=$(PY_MAIN_LIB) -t flt-backend:local .

clean: ## Удалить кэши и временные артефакты
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .coverage htmlcov
