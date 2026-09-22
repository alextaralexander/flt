# CLAUDE.md

Канонический свод правил для AI-агентов и людей, работающих в этом репозитории.
`.cursor/rules/*` и `.claude/` ссылаются на этот файл — здесь источник истины.

## Назначение

Шаблон production-FastAPI-сервиса: HTTP API + брокер **Kafka** (на FastStream),
метрики (Prometheus), трассировка (OpenTelemetry), структурированное логирование (structlog +
OpenSearch), секреты (Vault), миграции (Alembic), JWT-авторизация и permissions.
**AsyncAPI** генерируется автоматически из FastStream-роутеров.

## Команды (единая точка входа — `make`)

Не угадывай команды — используй `Makefile`. Полный список: `make help`.

| Действие | Команда |
| --- | --- |
| Установить зависимости | `make install` |
| Запустить dev-сервер | `make dev` |
| Тесты / с покрытием | `make test` / `make test-cov` |
| Тесты без локальной инфраструктуры | `make test-docker` (одноразовый Postgres) |
| Формат (ruff format + импорты) | `make format` |
| Линт (ruff check) | `make lint` / `make lint-fix` |
| Типы (mypy strict) | `make typecheck` |
| Security (bandit+secrets) | `make security` |
| **Полная проверка (DoD)** | **`make check`** |
| Миграция (создать) | `make makemigration name="add_x"` |
| Применить миграции | `make migrate` |
| Скаффолд REST-сущности | `make scaffold-entity name=Order` |
| Скаффолд Kafka-сабскрайбера | `make scaffold-subscriber topic=ORDER_CREATED value="svc.order.created.01"` |
| Локальная инфраструктура | `make compose-up` / `make compose-down` |
| AsyncAPI-эндпоинты | `make asyncapi` |
| Пересобрать uv.lock | `make lock` |

## Рабочие правила

- Делай минимальное безопасное изменение, которое полностью решает задачу.
- Сохраняй существующий стиль проекта, структуру слоёв и соглашения по именованию.
- Не переписывай несвязанный код и не откатывай чужие изменения.
- При изменении публичного поведения обновляй тесты, схемы и docstring-и рядом с изменением.
- Для нового функционала **сначала попробуй скаффолдер** (`make scaffold-*` / `python -m cli`),
  затем дорабатывай сгенерированный код — так стиль остаётся единым.

## Definition of Done

Задача завершена, только если выполнено всё применимое:

1. Код следует архитектуре слоёв (см. ниже) и не нарушает направление импортов.
2. Обновлены/добавлены тесты рядом с затронутой областью.
3. `make check` проходит локально (format → lint → typecheck → security → tests).
   Если команда не запускается из-за окружения/зависимостей — явно укажи это в результате, не скрывай.
4. Docstring-и приведены в соответствие с поведением (контракт ниже).

## Архитектура и направление импортов

```
configs/        # настройки окружения (stands), брокеров, Vault, запуск
app/
  api/          # HTTP-слой
    controllers/  # модульный APIRouter; сервисы приходят через Depends()
    services/     # бизнес-логика (наследует py_main_lib.BaseService)
    dao/          # доступ к БД (наследует py_main_lib.BaseDAO)
    schemas/      # Pydantic DTO запросов/ответов
  brokers/
    kafka/        # subscribers / publishers / schemas / services / middlewares
  core/           # общая инфраструктура: dao(БД/redis), security, metrics,
                  # middlewares, telemetry, logging, schemas, exceptions
tests/            # структура зеркалит app/ (api/, brokers/, core/)
cli/              # typer-скаффолдер (генерация сущностей и сабскрайберов)
```

Структура **слоистая** (controllers/services/dao), а не доменная (Netflix Dispatch-стиль):
для микросервиса с 1–5 сущностями это осознанный trade-off — меньше вложенности,
скаффолдер генерирует по одному файлу на слой. Если сервис вырастает в десятки доменов —
пересматривайте в пользу доменных модулей.

**Направление зависимостей (нарушать нельзя):**

- `controllers` → `services` → `dao` → `core/dao/models`. Контроллер **не** ходит в DAO напрямую.
- `api` и `brokers` могут зависеть от `core`, но `core` **не** зависит от `api`/`brokers`;
  `api` не импортирует `brokers` (общие схемы ошибок — в `app/core/schemas.py`).
- `schemas` (DTO) не импортируют слои бизнес-логики.
- Брокер-`services` инкапсулируют бизнес-логику обработки сообщений; сами хендлеры
  (`subscribers.py`) тонкие: разбор сообщения → лог-контекст → вызов сервиса.
  Сервис и в контроллеры, и в брокер-хендлеры приходит через `Depends()`.

## Формат ошибок HTTP

- Все ошибки HTTP-слоя отдаются в едином конверте `ErrorResponseV1`: доменные,
  валидационные (422), `HTTPException` (см. `app/api/exception_handlers.py`)
  и 500 из logging-middleware. Новые хендлеры строй через `error_envelope`.
- Служебные эндпоинты `/info` и `/system-metrics` закрыты permissions
  (`MetricsPermissions`); `/health`, `/ready`, `/metrics` открыты — их опрашивают
  probes и Prometheus (эти пути исключены из access-лога).

## Добавление REST-эндпоинта

1. `make scaffold-entity name=Order` — создаст schema/dao/service/controller(+тест) и
   подключит роутер в `app/api/controllers/__init__.py`.
2. Допиши поля модели в `app/core/dao/models.py`.
3. Создай миграцию: `make makemigration name="add_order"`, проверь файл, затем `make migrate`.
4. Уточни permissions в `app/core/security/permissions.py`.

Подробный разбор слоёв — раздел «Инструкции» в `README.md`.

## Добавление брокер-консьюмера (Kafka)

1. `make scaffold-subscriber topic=ORDER_CREATED value="svc.order.created.01"` — создаст
   схему сообщения, добавит топик в `KafkaSubscriberTopics`, допишет subscriber в
   `app/brokers/kafka/subscribers.py` и создаст сервис-обработчик.
2. Сабскрайберы регистрируются автоматически за счёт импорта модуля `subscribers` в `app/main.py`.
3. Реализуй бизнес-логику в сгенерированном `*_service.py`.
4. Добавь тест в `tests/brokers/kafka/`.

## Жизненный цикл ресурсов

- Приложение собирает фабрика `create_app()` в `app/main.py`; тесты создают
  собственный экземпляр (см. `tests/conftest.py`) и не мутируют продовый.
- Внешние ресурсы (engine БД, Redis-клиент, телеметрия) создаются **лениво** и управляются
  `lifespan`-ом в `app/main.py`: startup — создание/прогрев, shutdown — освобождение.
- Не создавай подключения на уровне модуля: импорт кода приложения (Alembic, скрипты, тесты)
  не должен иметь побочных эффектов.
- Осознанное исключение из правила выше: `configs/*` инстанцируют Settings при импорте
  (включая разовое чтение Vault для секретов) — trade-off ради простоты
  `from configs.settings import settings`. Новых сетевых вызовов туда не добавлять.
- Redis-клиент один на процесс (`app/core/dao/caching/redis_conn.py`); engine БД — через
  `get_engine()`/`get_session()`.

## Брокеры и AsyncAPI

- FastStream-роутер `kafka_router` подключается в `app/main.py`;
  хендлеры регистрируются импортом модулей `publishers` и `subscribers`.
- AsyncAPI отдаётся по `/asyncapi/kafka` (`schema_url` в роутере).
  `publishers.py` существуют в т.ч. ради отображения исходящих топиков в AsyncAPI — не удаляй.
- Любой новый топик описывается отдельной Pydantic-схемой в `schemas/{publisher,subscriber}_messages/`
  и регистрируется в соответствующем `enums.py`.
- **Публикация из работающего приложения** — только через брокер роутера
  (`await kafka_router.broker.publish(...)`): он уже подключён и подменяется `Test*Broker`
  в тестах. `async with broker` закрывает общее соединение — не использовать.
- Ошибки обработки Kafka-сообщений публикуются в callback-топики
  (маппинг `KAFKA_ERROR_TOPIC_BY_SOURCE` в `app/brokers/topics_handlers.py`).
- Middleware — конвенция FastStream 0.6/0.7: без параметров регистрируются **классом**
  (брокер сам создаёт `cls(msg, context=ctx)`); с параметрами — настроенным инстансом,
  чей `__call__(self, msg, /, *, context)` возвращает per-message инстанс.
  Тело сообщения — только `await message.decode()` (`decoded_body` удалён);
  publish-путь получает `PublishCommand` (`cmd.body` / `cmd.destination` / `cmd.add_headers`).
- Специфика FastStream 0.7 (текущая линия, потолок `<0.8`): middleware только на уровне
  брокера/роутера (subscriber-level удалены); настройки подтверждения — через
  `ack_policy=AckPolicy.*` (`no_ack`/`ack_first` удалены); остановка брокера — `broker.stop()`
  (`broker.close()` удалён).

## Контракт docstring-ов

Docstring-и — часть контракта функций, классов и методов. Наличие обязательно
для каждого модуля, класса и функции — форсируется ruff (правила D1xx в pyproject);
заглушки вида `"""do_stuff."""` запрещены — пиши одну содержательную фразу.

- Меняется логика — обновляй docstring в том же изменении.
- Реализация разошлась с docstring — сначала приводи реализацию к описанному контракту.
- Меняй только docstring вместо логики лишь тогда, когда задача явно меняет ожидаемое поведение.
- Меняется и поведение, и описание — тесты должны отражать новый контракт.
- Стиль: **Google-style**, кратко, по поведению и побочным эффектам; не оставляй устаревшие
  описания параметров/возвращаемых значений/исключений/side-effect-ов.

## Тестирование

- Тесты преимущественно интеграционные; структура `tests/` зеркалит `app/`.
- Аутентификация HTTP-тестов — через `dependency_overrides` одной точки `get_current_user`
  (см. `tests/conftest.py`); брокерные no_db-тесты подменяют `check_token`.
- Покрытие защищено порогом `fail_under` (pyproject) — не отключай его, добавляй тесты.
- Шаблон тела теста — **Arrange / Act / Assert** (+ `Clean`, если создавали данные в БД).
- Добавляешь ветвление, обработку ошибок или runtime-поведение — добавляй/обновляй тесты рядом.
- Если тест падает из-за уже существующей проблемы — не скрывай и не откатывай её, зафиксируй в результате.
- Защита от запуска на реальной БД: `TEST_MODE` берётся из `envs/.test.env` —
  pytest-оверлея поверх стенда local (pytest загружает его через `env_files`;
  переменные окружения имеют приоритет). Не путать с `envs/test/` — это
  конфигурация деплой-стенда test, к pytest она отношения не имеет.

## Безопасность

- Секреты только через Vault/env, **никогда** в коде или коммитах. Проверка — `make security`
  (bandit + detect-secrets). Базлайн ложных срабатываний — `.secrets.baseline`.
- Не логируй токены/payload с чувствительными данными; соблюдай структурный формат логов.
- О процессе раскрытия уязвимостей — `SECURITY.md`.

## Зависимости и окружение

- Менеджер пакетов — **uv**. Версия Python — `.python-version`.
- Источник истины по зависимостям — `pyproject.toml` (`[project]` + dev-группа), лок — `uv.lock`.
- Docker-сборка ставит зависимости напрямую из `uv.lock` (multi-stage, см. `Dockerfile`);
  `requirements.txt` больше не используется.
- Внутренняя `py_main_lib` ставится отдельно (private registry / локальный boilerplate),
  её нет в `pyproject` — это ожидаемо.

## Анти-паттерны (не делать)

- Бизнес-логика в контроллере или в хендлере брокера.
- Прямой доступ к БД из контроллера, минуя service/DAO.
- Модульный синглтон или ручное создание сервиса в контроллере и брокер-хендлере
  (`service = XService()`) — сервис приходит через `Depends()`, иначе его нельзя
  подменить в тестах.
- Ответ с ошибкой вне конверта `ErrorResponseV1` (см. «Формат ошибок HTTP»).
- Сырой `request.url.path` в качестве метки метрик — только шаблон маршрута
  (см. `PrometheusMiddleware`), иначе взрыв кардинальности.
- Создание подключений (engine, Redis, брокеры) на уровне модуля — только лениво/в lifespan.
- `async with router.broker` в работающем приложении (закрывает общее соединение).
- Импорт `app/api` или `app/brokers` из `app/core`; импорт `app/brokers` из `app/api`.
- Новый топик без отдельной схемы и без записи в `enums.py`.
- Удаление `publishers.py` («не используется» — он нужен для AsyncAPI).
- Секреты, токены, пароли в коде/конфигах/тестах.
- Широкие `except:` без переброса/логирования; молчаливое проглатывание ошибок.
- Коммит без прохождения `make check`.

## Claude Code

- Прежде чем писать новый функционал — проверь, есть ли скаффолдер:
  `make scaffold-entity name=...` или `make scaffold-subscriber topic=... value=...`
  (см. `.claude/commands/`). Генерируй каркас скаффолдером, затем дорабатывай.
- Готовые слэш-команды: `/add-endpoint`, `/add-subscriber`, `/verify`
  (определены в `.claude/commands/`).
- Навыки (skills) в `.claude/skills/` описывают сквозные сценарии: добавление фичи и консьюмера.
- Перед завершением задачи всегда прогоняй `make check` (Definition of Done выше).
- Правила архитектуры и стиля продублированы для Cursor в `.cursor/rules/*.mdc` — держи их
  и этот файл синхронными при изменении соглашений.
- Не редактируй сгенерированный `uv.lock` вручную — используй `make lock`.
- Не коммить секреты; перед коммитом отрабатывает pre-commit
  (ruff-check + ruff-format + uv-lock + bandit + detect-secrets).
