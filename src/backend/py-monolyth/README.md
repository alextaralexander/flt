# flt-backend

Модульный монолит FLT на FastAPI (Python 3.14): REST, Kafka (FastStream), PostgreSQL со схемой
на модуль, Redis, Prometheus, OpenTelemetry, JSON-логи. Правила разработки — [CLAUDE.md](CLAUDE.md),
архитектурные решения — `Analytics/ADR/` (ADR-001…ADR-015), требования — `Analytics/Specs/`.

## Быстрый старт

Нужны [uv](https://docs.astral.sh/uv/) (Python 3.14 он скачает сам) и Docker.

```sh
cd src/backend/py-monolyth
make install        # uv sync: зависимости и py-main-lib (path-зависимость ../py-main-lib)
make compose-up     # PostgreSQL, Redis, Kafka из deploy/docker-compose
make migrate        # миграции всех модулей реестра (alembic -n <module> upgrade head)
make dev            # роль all: REST на :8000 и консьюмеры Kafka, автоперезагрузка
```

Проверка: `curl http://127.0.0.1:8000/v1/health`, документация — http://127.0.0.1:8000/api/docs.
Стенд выбирает `STAND_NAME` (по умолчанию `local`, образец — `.env.template`); настройки стенда —
`envs/<stand>/`. Секреты вне local — только переменные окружения (ADR-013).

## Роли запуска

Один образ, роль — переменная `APP_ROLE` (`python -m app`, ADR-004):

| Роль | Что делает | Порт |
| --- | --- | --- |
| `api` | REST `/api/v1/<module>`, `/v1/health`, `/v1/ready`, `/v1/metrics`, `/api/docs` | 8000 |
| `worker` | консьюмеры Kafka, `/v1/*`, `/asyncapi/kafka` | 8001 |
| `all` | `api` + `worker` в одном процессе (local, pytest) | 8000 |
| `migrate` | миграции всех модулей, затем выход | — |
| `media_agent` | AI-преподаватель в LiveKit — этап 6 | — |

```sh
make run            # роль migrate, затем api — как в Docker
make run-worker     # роль worker
make docker-build   # образ flt-backend:local (py-main-lib — build-context)
```

## Модули

Доменный модуль — пакет `app/modules/<module>/` с публичным API `public/`, своей схемой PostgreSQL,
миграциями, настройками `<MODULE>_` и правами `<module>:<resource>:<action>`. Реестр —
`app/modules/registry.py`, границы проверяет import-linter (`make arch`).

```sh
make scaffold-module name=identity
make scaffold-entity module=identity name=User
make scaffold-subscriber module=notifications topic=USER_DELETED value="flt.identity.user_deleted.v1"
make makemigration module=identity name="add_user" && make migrate
```

## Проверки

```sh
make check          # format → lint → typecheck → arch → security → test-cov (порог 75 %)
make test-docker    # тесты на одноразовом PostgreSQL
```
