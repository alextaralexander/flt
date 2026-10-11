# CLAUDE.md

Канонический свод правил для AI-агентов и людей, работающих с бэкендом FLT (`src/backend/py-monolyth`).
Правила уровня репозитория — корневой `CLAUDE.md`; при расхождении действует он и ADR из `Analytics/ADR/`.

## Назначение

`flt-backend` — модульный монолит на FastAPI: REST и служебные эндпоинты, Kafka на FastStream
(AsyncAPI генерируется автоматически), PostgreSQL (схема на модуль) и Redis, метрики Prometheus,
трассировка OpenTelemetry (экспорт выключен до этапа 4), структурированные JSON-логи в stdout,
проверка JWT и permissions. Один образ запускается в ролях `api`, `worker`, `all`, `migrate`,
`media_agent` (`APP_ROLE`, ADR-004).

## Команды (единая точка входа — `make`)

Не угадывай команды — используй `Makefile`. Полный список: `make help`.

| Действие | Команда |
| --- | --- |
| Установить зависимости (py-main-lib — path-зависимость uv) | `make install` |
| Dev-сервер с автоперезагрузкой (роль `all`) | `make dev` |
| Как в Docker: роль `migrate`, затем `api` / роль `worker` | `make run` / `make run-worker` |
| Тесты / с покрытием (порог 75 %) | `make test` / `make test-cov` |
| Тесты без локальной инфраструктуры | `make test-docker` (одноразовый Postgres) |
| Формат / проверка формата | `make format` / `make format-check` |
| Линт (ruff check) | `make lint` / `make lint-fix` |
| Типы (mypy strict) | `make typecheck` |
| Границы модулей (import-linter) | `make arch` |
| Security (bandit + detect-secrets) | `make security` |
| **Полная проверка (DoD)** | **`make check`** = format → lint → typecheck → arch → security → test-cov |
| Модуль / REST-сущность / Kafka-консьюмер | `make scaffold-module name=…`, `make scaffold-entity module=… name=…`, `make scaffold-subscriber module=… topic=… value=…` |
| Модули реестра | `make list-modules` |
| Миграции: применить / создать / откатить | `make migrate`, `make makemigration module=… name=…`, `make migrate-downgrade module=… rev=…` |
| Локальная инфраструктура | `make compose-up` / `make compose-down` |
| Пересобрать uv.lock | `make lock` |

## Рабочие правила

- Делай минимальное безопасное изменение, которое полностью решает задачу.
- Сохраняй существующий стиль проекта, структуру слоёв и соглашения по именованию.
- Не переписывай несвязанный код и не откатывай чужие изменения.
- При изменении публичного поведения обновляй тесты, схемы и docstring-и рядом с изменением.
- Для нового функционала **сначала скаффолдер** (`make scaffold-*` / `python -m cli`),
  затем дорабатывай сгенерированный код — так стиль остаётся единым. Сгенерированный код
  проходит `make check` без правок (это проверяют `tests/cli/`).

## Definition of Done

1. Код следует раскладке модулей и слоёв (см. ниже), `make arch` зелёный.
2. Обновлены/добавлены тесты рядом с затронутой областью.
3. `make check` проходит локально. Если команда не запускается из-за окружения — явно укажи это.
4. Docstring-и приведены в соответствие с поведением (контракт ниже).

## Архитектура и направление импортов (ADR-002)

```
configs/                 # настройки процесса: стенды, PostgreSQL, Redis, Kafka (секреты — только env)
app/
  __main__.py            # python -m app: процесс роли APP_ROLE, `healthcheck`
  main.py                # create_app() (api/all), create_worker_app() (worker) — по реестру модулей
  core/                  # shared kernel без бизнес-логики (подпакеты — только из SYS-01-R10)
    modules.py           # ModuleDefinition, load_modules()
    http/                # конверт ErrorResponseV1, обработчики исключений, access-лог
    kafka/               # брокер процесса (create_broker), базовые схемы сообщений
    dao/db_helpers/      # engine по роли, сессии, module_metadata()/make_module_base(), общий env.py Alembic
    dao/caching/         # Redis-клиент процесса (standalone/Sentinel); ModuleRedis — этап 1 Г.4
    security/ logging/ metrics/ telemetry.py exceptions.py schemas.py
  modules/
    registry.py          # MODULES — модули в порядке зависимостей SYS-01
    <module>/
      module.py          # module = ModuleDefinition(...)
      public/            # ЕДИНСТВЕННОЕ, что импортируют другие модули
      api/               # router.py (APIRouter(prefix="/api/v1/<module-kebab>")) и контроллеры
      brokers/           # router.py (KafkaRouter), subscribers.py, topics.py, messages/, services/
      services/ dao/ models/ schemas/
      migrations/versions/   # ревизии Alembic только этого модуля
      settings.py        # <Module>Settings, env_prefix "<MODULE>_", envs/<stand>/<module>_<stand>.env
      permissions.py     # коды прав <module>:<resource>:<action> (SYS-06)
cli/                     # скаффолдер (add-module, add-entity, add-subscriber, list-modules)
tests/                   # зеркалит app/: tests/core, tests/modules/<module>, tests/cli, tests/configs
```

**Направление зависимостей (нарушать нельзя, проверяет `make arch`):**

- Модуль импортирует из чужого модуля **только** `app.modules.<other>.public` и только вниз
  по реестру (контракты `modules-public-api-only`, `modules-dependency-order`).
- Внутри модуля: `api | brokers` → `public` → `services` → `dao` → `models`; `schemas`,
  `settings`, `permissions` доступны любому слою. Контроллер не ходит в DAO напрямую.
- `app.core` и `configs` не импортируют `app.modules` (`core-does-not-import-modules`).
- Модули не импортируют `redis` и `app.core.dao.caching.redis_conn` (только `ModuleRedis`, Г.4),
  брокер Kafka `app.core.kafka.broker` (публикация — через outbox, Г.4), `aioboto3`, `botocore`,
  `opensearchpy`, `qdrant_client`.
- У модуля своя схема PostgreSQL `<module>`; внешних ключей и `relationship` между схемами нет,
  ссылки на чужие сущности — `UUID` без `ForeignKey`.

## Роли запуска (ADR-004)

| `APP_ROLE` | Процесс | Порт |
| --- | --- | --- |
| `api` | uvicorn: REST модулей, `/v1/health`, `/v1/ready`, `/v1/metrics`, `/api/docs`, `/api/openapi.json`; без Kafka | 8000 |
| `worker` | `AsgiFastStream`: консьюмеры Kafka модулей, `/v1/*`, `/asyncapi/kafka` | `WORKER_HTTP_PORT` (8001) |
| `all` | `api` + брокер `worker` в одном процессе; по умолчанию только на стенде local | 8000 |
| `migrate` | `alembic -n <module> upgrade head` по модулям реестра, выход 0 | — |
| `media_agent` | этап 6 (ADR-015); сейчас завершается с кодом 2 | — |

Инстансы при старте миграции не выполняют. uvicorn роли `api` работает с `proxy_headers=True` и
`FORWARDED_ALLOW_IPS` (ADR-012). Пул БД и `statement_timeout` задаются по роли (`engine_options`).

## Формат ошибок HTTP

- Все ошибки HTTP-слоя отдаются в едином конверте `ErrorResponseV1`: доменные,
  валидационные (422), `HTTPException` (`app/core/http/exception_handlers.py`)
  и 500 из logging-middleware. Новые хендлеры строй через `error_envelope`.
- Служебные `/v1/health`, `/v1/ready`, `/v1/metrics` открыты (их опрашивают HAProxy, probes и
  Prometheus) и исключены из access-лога; снаружи они недоступны (ADR-012).

## Добавление модуля, REST-эндпоинта, консьюмера

1. `make scaffold-module name=<module>` — пакет модуля, строка в `MODULES`, контракты 1–3 в
   `.importlinter`, секция `[<module>]` в `alembic.ini`, `envs/<stand>/<module>_<stand>.env`,
   `tests/modules/<module>/`. Подтверди место модуля в `MODULES` по карте SYS-01.
2. `make scaffold-entity module=<module> name=Order` — модель, схемы, DAO, сервис, контроллер,
   права, подключение роутера и тест сервиса; затем поля модели,
   `make makemigration module=<module> name="add_order"`, проверка ревизии, `make migrate`.
3. `make scaffold-subscriber module=<module> topic=ORDER_PLACED value="flt.<producer>.order_placed.v1"` —
   схема в `brokers/messages/`, обработчик в `brokers/services/`, член enum в `brokers/topics.py`,
   хендлер в `brokers/subscribers.py` с `group_id="flt.<module>.<handler>"`; формат топика — SYS-04.

## Жизненный цикл ресурсов

- Приложения собирают фабрики `create_app()` и `create_worker_app()`; тесты создают собственные
  экземпляры и не мутируют процессные. Импорт кода приложения не имеет побочных эффектов.
- Внешние ресурсы (engine БД, Redis-клиент, телеметрия, брокер) создаются **лениво** и
  освобождаются в lifespan роли.
- Исключение: `configs/*` инстанцируют Settings при импорте (без сетевых вызовов).
- Состояние между запросами в памяти процесса и на диске инстанса **не хранится**
  (корневой CLAUDE.md, «Масштабирование и состояние»); `lru_cache`/`cache` на функциях,
  читающих PostgreSQL или Redis, запрещены.

## Брокеры и AsyncAPI

- Брокер процесса — `faststream.kafka.KafkaBroker` из `create_broker()`; Kafka-роутеры модулей
  (`faststream.kafka.KafkaRouter`) подключаются по реестру в ролях `worker` и `all`.
- AsyncAPI — `/asyncapi/kafka` на служебном порту воркера.
- Сервисы в хендлеры приходят через `Depends()` FastStream; тесты — `TestKafkaBroker`.
- Публикация из модулей — только через `OutboxPublisher` (этап 1 Г.4); прямой `broker.publish`
  в модулях запрещён. Ретраи и DLQ вместо callback-топиков — этап 1 Г.4 (ADR-004).
- Middleware — конвенция FastStream 0.7 (потолок `<0.8`): только на уровне брокера/роутера,
  подтверждение — `ack_policy=AckPolicy.*`, остановка брокера — `broker.stop()`.

## Контракт docstring-ов

Docstring-и — часть контракта функций, классов и методов. Наличие обязательно
для каждого модуля, класса и функции — форсируется ruff (правила D1xx в pyproject);
заглушки вида `"""do_stuff."""` запрещены — пиши одну содержательную фразу.

- Меняется логика — обновляй docstring в том же изменении.
- Реализация разошлась с docstring — сначала приводи реализацию к описанному контракту.
- Стиль: **Google-style**, кратко, по поведению и побочным эффектам.

## Тестирование

- Структура `tests/` зеркалит `app/`; тесты модулей — `tests/modules/<module>/`.
- Аутентификация HTTP-тестов — через `dependency_overrides` одной точки `get_current_user`
  (`tests/conftest.py`). До `TokenVerifier` (этап 1 Г.4) `check_token` отклоняет любой токен.
- Миграции всех модулей реестра накатываются фикстурой `db_migrate` один раз на сессию.
- Покрытие защищено порогом `fail_under` (pyproject) — не отключай его, добавляй тесты.
- Шаблон тела теста — **Arrange / Act / Assert** (+ `Clean`, если создавали данные в БД).
- Защита от запуска на реальной БД: `TEST_MODE` берётся из `envs/.test.env` — pytest-оверлея
  поверх стенда local. `envs/test/` — конфигурация деплой-стенда test, к pytest отношения не имеет.

## Безопасность и конфигурация (ADR-013)

- Секреты — только переменные окружения: поля `SecretStr` без значения по умолчанию, отсутствие
  секрета останавливает старт. Клиента Vault в коде нет: в Kubernetes секреты подаёт External
  Secrets Operator, в docker-compose — `.env`.
- В `envs/` — только несекретные параметры; тестовые значения стенда local помечаются
  `# pragma: allowlist secret`. Проверка — `make security` (bandit + detect-secrets).
- Не логируй токены и данные пользователей; соблюдай структурный формат логов.

## Зависимости и окружение

- Менеджер пакетов — **uv**, Python 3.14 (`.python-version`).
- Источник истины — `pyproject.toml` (`[project]` + dev-группа), лок — `uv.lock` (только `make lock`).
- `py-main-lib` — path-зависимость uv (`[tool.uv.sources]`, `../py-main-lib`); её зависимости
  учитывает `uv.lock`; в Docker она приходит build-context-ом `py-main-lib`.

## Анти-паттерны (не делать)

- Бизнес-логика в контроллере или в хендлере брокера; прямой доступ к БД из контроллера.
- Импорт внутренних пакетов чужого модуля (только `public`), внешний ключ в чужую схему,
  прямой Redis-клиент или брокер Kafka в модуле.
- Модульный синглтон или ручное создание сервиса в контроллере и хендлере — только `Depends()`.
- Ответ с ошибкой вне конверта `ErrorResponseV1`.
- Сырой `request.url.path` в метках метрик — только шаблон маршрута (`PrometheusMiddleware`).
- Создание подключений на уровне модуля; состояние в памяти процесса между запросами.
- Миграции или DDL при старте инстанса.
- Секреты, токены, пароли в коде/конфигах/тестах.
- Широкие `except:` без переброса/логирования; молчаливое проглатывание ошибок.
- Коммит без прохождения `make check`.
