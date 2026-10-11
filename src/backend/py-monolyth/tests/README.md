# Тесты

Структура каталога зеркалит `app/`: тесты shared kernel — `tests/core/...`, тесты модулей —
`tests/modules/<module>/...` (ADR-002), скаффолдер — `tests/cli/`, настройки — `tests/configs/`.

## Запуск

```shell
make test          # локальный Postgres (поднимается через make compose-up)
make test-docker   # одноразовый Postgres в docker — без локальной инфраструктуры
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
  `env_files`); там же живёт `TEST_MODE=true` — защита от запуска на реальной БД.
- Нужны PostgreSQL и Redis стенда local (адреса переопределяются `PG_PORT`, `REDIS_PORT` и т.п.).
- Каталог `envs/test/` — конфигурация деплой-стенда test, к pytest отношения не имеет.
- Тестовые значения в коде читаются из `tests/settings.py` (`test_settings`), а не из боевого `Settings`.
