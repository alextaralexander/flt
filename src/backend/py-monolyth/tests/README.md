# Тесты

Структура каталога зеркалит `app/`: тесты компонента лежат в одноимённом пути
(`app/api/controllers/...` → `tests/api/controllers/...`).

## Запуск

```shell
make test          # локальный Postgres (поднимается через make compose-up)
make test-docker   # одноразовый Postgres в docker — без локальной инфраструктуры
make test-cov      # с отчётом покрытия; порог — fail_under в pyproject.toml
```

## Конвенции

- **Arrange / Act / Assert** (+ `Clean`, если тест создавал данные в БД) — размечайте блоки комментариями.
- **`@pytest.mark.no_db`** — тест не трогает БД (unit-тесты, брокерные тесты): для него не
  накатываются миграции, а broker-auth подменяется автоматически (см. `conftest.py`).
- **Аутентификация HTTP-тестов** — через `dependency_overrides` одной зависимости
  `get_current_user` (даёт fixture `overridden_app`); проверка permissions при этом остаётся настоящей.
- **Брокеры** — только `TestKafkaBroker`, реальная Kafka тестам не нужна.
- **Fixtures**: общие — в `conftest.py`; узкоспециальные — в `tests/fixtures/` рядом с сущностью.
- `@pytest.mark.asyncio` не нужен: включён `asyncio_mode = "auto"`.

## Окружение

- Тесты идут на стенде **local** с оверлеем `envs/.test.env` (его загружает pytest через
  `env_files`); там же живёт `TEST_MODE=true` — защита от запуска на реальной БД.
- Каталог `envs/test/` — конфигурация деплой-стенда test, к pytest отношения не имеет.
- Тестовые значения в коде читаются из `tests/settings.py` (`test_settings`), а не из боевого `Settings`.
