# BOILERPLATE.md — манифест боилерплейта `python-boilerplate` (дефолтный Python-профиль)

> Манифест читается треком backend на фазе INTAKE (`IMPLEMENTATION_WORKFLOW_BACKEND.md`) и превращается в
> «Boilerplate profile» в `00_build_plan.md`. Формат — `boilerplates/BOILERPLATE_TEMPLATE.md`;
> правило — `guidelines/backend/backend-impl-settings.md`, раздел 1.1.

## 1. Стек
- Язык/версия: Python 3.13 (`.python-version`)
- Фреймворк: FastAPI (+ Pydantic v2)
- ORM и миграции: SQLAlchemy 2.0 (async) + Alembic
- Брокеры/кэш: FastStream (Kafka), Redis
- Общие библиотеки: `py-main-lib` (`BaseService`, `BaseDAO`, `BaseEntityModel`, `transaction_context`,
  `filter_utils`, `security.schemas`) — берётся из `boilerplates/py-main-lib` (приватный registry недоступен)

## 2. Слои — куда генерировать код (SA-артефакт → путь в боилерплейте)
Полная таблица с примечаниями — `guidelines/backend/backend-impl-settings.md`, раздел 4. Кратко:
| Вход (контракт-пакет) | Куда генерируем (копия боилерплейта) |
|-----------------------|--------------------------------------|
| Модель persisted БД (ER Mermaid) | `app/core/dao/models.py` + Alembic-миграция `app/core/dao/db_helpers/migrations/versions/` |
| DTO (JSON Schema) | `app/api/schemas/<entity>_schema.py` (Pydantic) |
| REST API | `app/api/controllers/<entity>_controller.py` + регистрация в `app/api/controllers/__init__.py` (`v1_router`) |
| Backend-алгоритмы | `app/api/services/<entity>_service.py` (override `BaseService`) |
| Async API | `app/brokers/kafka/...` (только если async-контракт есть в SA) |
| Права/роли | `app/core/security/permissions.py` (enum из спеки, не заглушки) |
| Тексты сообщений | коды/тексты ошибок в коде и тестах |
| AC / use cases | `tests/api/...` |

## 3. Команды (единая точка входа — make)
- Установка зависимостей: `make install` (uv sync + py-main-lib из локального клона)
- Полная проверка (DoD): `make check` (format → lint → mypy strict → security → tests)
- Тесты: `make test` / `make test-docker` (одноразовый Postgres, без локальной инфраструктуры)
- Запуск сервиса (dev): `make dev`; prod-режим: `make run` (порт по умолчанию: 8000, health: `/v1/health`)
- Миграции БД: `make migrate` (схему создаёт Alembic)
- Скаффолд: `make scaffold-entity name=<Entity>` / `make scaffold-subscriber topic=<CONST> value="<topic>"`

## 4. OpenAPI-conformance
FastAPI самоописывается: поднять сервис в smoke-режиме и выгрузить `GET /openapi.json`; сверять пути+методы,
имена/состав схем DTO и коды ответов с контрактом `assets/analysis/<task>/04_specs/rest-api/<service>_openapi.yaml`.

## 5. Zero-infra fallback
- Встроенное хранилище: SQLite/in-memory (aiosqlite), один процесс на venv; `PYTHONPATH` на корень сервиса.
- Отключить внешние системы: `OPEN_SEARCH_LOGS_ENABLED=false`; брокеры не поднимать (FastStream коннектит их на
  старте — smoke-режим без подписчиков).

## 6. Конвенции
- Слоистая архитектура controllers → services → dao; конвенции — `CLAUDE.md` внутри боилерплейта
  (наследуются копией сервиса).
- Google-style docstrings; контракт docstring-ов обязателен.
- Не удалять `core/dao/caching` (нужен кэш-сервисам); скаффолдер — `python -m cli add-entity/add-subscriber`.
- Боилерплейт read-only: правки только в копии `backend/build/<service>/`.
