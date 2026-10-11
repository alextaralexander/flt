## ---------------------------------------------------------------------------
## flt-backend — единая точка входа для разработки и агентов.
## Запусти `make help`, чтобы увидеть все цели.
## ---------------------------------------------------------------------------

# Запускаем инструменты в окружении uv. Если uv недоступен — переопредели: make RUN= ...
RUN ?= uv run
COMPOSE_FILE ?= ../../../deploy/docker-compose/docker-compose.yml
# Инфраструктура для запуска сервиса на хосте (сам сервис в compose — сервис `backend`).
COMPOSE_INFRA ?= postgres redis kafka
# Путь до py-main-lib: path-зависимость uv (pyproject.toml) и build-context Docker-образа.
PY_MAIN_LIB ?= ../py-main-lib

.DEFAULT_GOAL := help
.PHONY: help install dev run run-worker test test-cov test-docker format format-check lint lint-fix typecheck arch \
        security secrets-scan check migrate makemigration migrate-downgrade asyncapi \
        scaffold-module scaffold-entity scaffold-subscriber list-modules lock pre-commit \
        compose-up compose-down docker-build clean

help: ## Показать список доступных команд
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# --- Окружение и зависимости (G8: uv) --------------------------------------

install: ## Установить зависимости из uv.lock (py-main-lib — path-зависимость uv)
	uv sync --all-groups

lock: ## Пересобрать uv.lock из pyproject.toml
	uv lock

# --- Запуск -----------------------------------------------------------------

dev: ## Dev-сервер с автоперезагрузкой: роль all (api + брокер Kafka), порт 8000
	APP_ROLE=all $(RUN) uvicorn app.main:create_app --factory --reload --host $${FAST_API_HOST:-127.0.0.1} --port $${FAST_API_PORT:-8000}

run: migrate ## Как в Docker: роль migrate (make migrate), затем роль api (python -m app)
	APP_ROLE=api $(RUN) python -m app

run-worker: ## Роль worker: консьюмеры Kafka и служебный HTTP на WORKER_HTTP_PORT (8001)
	APP_ROLE=worker $(RUN) python -m app

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

arch: ## Границы модулей: import-linter по .importlinter (+ tests/architecture, когда появятся — Г.2)
	$(RUN) lint-imports
	@if [ -d tests/architecture ]; then $(RUN) pytest tests/architecture -p no:cacheprovider; fi

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

TEST_PG_CONTAINER ?= flt-backend-test-pg
TEST_PG_PORT ?= 54329

test-docker: ## Тесты в одноразовом Postgres (docker run), без локальной инфраструктуры
	@docker run -d --rm --name $(TEST_PG_CONTAINER) \
		-e POSTGRES_USER=ms_py_test -e POSTGRES_PASSWORD=ms_py_test -e POSTGRES_DB=flt \
		-p $(TEST_PG_PORT):5432 postgres:16-alpine >/dev/null
	@until docker exec $(TEST_PG_CONTAINER) pg_isready -U ms_py_test -d flt >/dev/null 2>&1; do sleep 0.5; done
	@PG_PORT=$(TEST_PG_PORT) $(RUN) pytest; STATUS=$$?; \
		docker stop $(TEST_PG_CONTAINER) >/dev/null; \
		exit $$STATUS

# --- Полная проверка (Definition of Done) ----------------------------------

# format мутирующий: агенту/разработчику дешевле автоформат, чем цикл «отказ → make format → повтор»;
# CI вызывает немутирующий format-check и остальные цели по отдельности (ADR-011).
check: format lint typecheck arch security test-cov ## Полная проверка перед коммитом (DoD)

pre-commit: ## Прогнать pre-commit на всех файлах
	$(RUN) pre-commit run --all-files

# --- База данных (Alembic: секция и схема на модуль, ADR-002) -------------

migrate: ## Применить миграции всех модулей реестра (alembic -n <module> upgrade head)
	@for m in $$($(RUN) python -m cli list-modules); do \
		echo "==> alembic -n $$m upgrade head"; \
		$(RUN) alembic -n $$m upgrade head || exit 1; \
	done

makemigration: ## Создать ревизию модуля: make makemigration module=identity name="add_user"
	@test -n "$(module)" || (echo "Укажи module=... и name=...: make makemigration module=identity name=\"add_user\"" && exit 1)
	@test -n "$(name)" || (echo "Укажи name=...: make makemigration module=$(module) name=\"add_x\"" && exit 1)
	$(RUN) alembic -n $(module) revision --autogenerate -m "$(name)"

migrate-downgrade: ## Откатить миграции модуля: make migrate-downgrade module=identity rev=base
	@test -n "$(module)" || (echo "Укажи module=... и rev=...: make migrate-downgrade module=identity rev=base" && exit 1)
	@test -n "$(rev)" || (echo "Укажи rev=... (ревизия или base): make migrate-downgrade module=$(module) rev=base" && exit 1)
	$(RUN) alembic -n $(module) downgrade $(rev)

# --- Скаффолдинг (ADR-002, раздел 3.7) --------------------------------------

scaffold-module: ## Создать доменный модуль: make scaffold-module name=identity
	@test -n "$(name)" || (echo "Укажи name=...: make scaffold-module name=identity" && exit 1)
	$(RUN) python -m cli add-module $(name)

scaffold-entity: ## Создать REST-сущность модуля: make scaffold-entity module=identity name=User
	@test -n "$(module)" || (echo "Укажи module=... и name=...: make scaffold-entity module=identity name=User" && exit 1)
	@test -n "$(name)" || (echo "Укажи name=...: make scaffold-entity module=$(module) name=User" && exit 1)
	$(RUN) python -m cli add-entity $(name) --module $(module)

scaffold-subscriber: ## Создать Kafka-консьюмер: make scaffold-subscriber module=m topic=USER_DELETED value="flt.identity.user_deleted.v1"
	@test -n "$(module)" || (echo "Укажи module=..., topic=... и value=...: make scaffold-subscriber module=m topic=USER_DELETED value=\"flt.identity.user_deleted.v1\"" && exit 1)
	@test -n "$(topic)" || (echo "Укажи topic=...: make scaffold-subscriber module=$(module) topic=USER_DELETED value=\"flt.identity.user_deleted.v1\"" && exit 1)
	@test -n "$(value)" || (echo "Укажи value=...: make scaffold-subscriber module=$(module) topic=$(topic) value=\"flt.<module>.<event>.v1\"" && exit 1)
	$(RUN) python -m cli add-subscriber $(topic) "$(value)" --module $(module)

list-modules: ## Показать модули реестра (app/modules/registry.py)
	@$(RUN) python -m cli list-modules

# --- AsyncAPI / инфраструктура ---------------------------------------------

asyncapi: ## Показать, где доступна AsyncAPI-документация (нужна запущенная роль worker)
	@echo "AsyncAPI Kafka: http://localhost:$${WORKER_HTTP_PORT:-8001}/asyncapi/kafka"
	@echo "Запусти 'make run-worker' и открой ссылку или сделай curl."

compose-up: ## Поднять локальную инфраструктуру (PostgreSQL, Redis, Kafka) из deploy/docker-compose
	docker compose -f $(COMPOSE_FILE) up -d --wait $(COMPOSE_INFRA)

compose-down: ## Остановить локальную инфраструктуру
	docker compose -f $(COMPOSE_FILE) down

docker-build: ## Собрать Docker-образ сервиса (py-main-lib — build-context)
	docker build --build-context py-main-lib=$(PY_MAIN_LIB) -t flt-backend:local .

clean: ## Удалить кэши и временные артефакты
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .coverage htmlcov
