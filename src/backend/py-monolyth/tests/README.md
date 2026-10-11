# Тесты

Структура каталога зеркалит `app/`: тесты shared kernel — `tests/core/...`, тесты модулей —
`tests/modules/<module>/...` (ADR-002), скаффолдер — `tests/cli/`, настройки — `tests/configs/`.

## Запуск

```shell
make compose-up    # локальные PostgreSQL (базы flt и flt_test), Redis и Kafka на loopback
make test          # тесты на базе flt_test и Redis DB 15 локальной инфраструктуры
make test-docker   # одноразовые PostgreSQL и Redis в docker — без локальной инфраструктуры
make test-cov      # с отчётом покрытия; порог — fail_under в pyproject.toml
```

## Конвенции

- **Arrange / Act / Assert** (+ `Clean`, если тест создавал данные в БД) — размечайте блоки комментариями.
- **`@pytest.mark.no_db`** — тест не трогает БД: для него не накатываются миграции.
- **Аутентификация HTTP-тестов** — через `dependency_overrides` одной зависимости
  `get_current_user` (даёт fixture `overridden_app`); проверка permissions при этом остаётся настоящей.
- **Брокеры** — только `TestKafkaBroker`, реальная Kafka тестам не нужна.
- **Миграции** — фикстура `db_migrate` накатывает модули реестра (`alembic -n <module>`) один раз на сессию.
- `@pytest.mark.asyncio` не нужен: включён `asyncio_mode = "auto"`.

## Окружение

- Тесты идут на стенде **local** с оверлеем `envs/.test.env` (его загружает pytest через
  `env_files`): `TEST_MODE=true`, отдельная база `PG_DATABASE=flt_test` (роль `flt`) и база
  Redis `REDIS_DB=15` того же экземпляра (SYS-10-R4, решение OQ-31) — запуск тестов не трогает
  данные стенда local (база `flt`, Redis DB 0). Фикстуры `db_migrate` и очистки Redis отказываются
  работать без `TEST_MODE`, на базе без суффикса `_test` и на базе Redis, отличной от 15.
- Нужны PostgreSQL и Redis стенда local (адреса переопределяются `PG_PORT`, `REDIS_PORT` и т.п.).
  Базу `flt_test` создаёт init-скрипт контейнера `deploy/docker-compose/postgres/init/01-create-test-db.sql`;
  том, созданный до перехода с роли `ms_py_test` на `flt`, пересоздаётся (`docker compose down -v`).
- Каталог `envs/test/` — конфигурация деплой-стенда test, к pytest отношения не имеет.
- Тестовые значения в коде читаются из `tests/settings.py` (`test_settings`), а не из боевого `Settings`.
