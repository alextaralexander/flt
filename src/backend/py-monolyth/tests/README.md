# Тесты

Структура каталога зеркалит `app/`: тесты shared kernel — `tests/core/...`, тесты модулей —
`tests/modules/<module>/...` (ADR-002), скаффолдер — `tests/cli/`, настройки — `tests/configs/`,
архитектурные тесты — `tests/architecture/` (границы модулей и хранение состояния: ADR-002 §3.6, SYS-05;
без БД, входят в `make arch`; каждый тест несёт маркер `@pytest.mark.req("SYS-NN-R<M>")`, SYS-10-R8).

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

## Маркеры (SYS-10-R12, R29, R30; SYS-05-R45)

Проверяются при сборе (`tests/support/markers.py`): нарушение — ошибка сбора, неизвестный маркер —
ошибка (`--strict-markers`).

| Маркер | Правило |
| --- | --- |
| `ac("STU-18-AC3")`, `req("SYS-05-R12")` | хотя бы один в `tests/core/`, `tests/modules/`, `tests/n_instances/`, `tests/architecture/` (там — обязательно `req`); можно на модуле: `pytestmark = pytest.mark.req(...)` |
| `n_instances` | только в `tests/n_instances/` и у каждого теста там; без `--stand-url` тест пропускается |
| `smoke` | смоук-набор «ходячего скелета» |
| `slow("причина")` | тест длиннее 5 с, обоснование обязательно |
| `quarantine(issue="#123", until="2026-10-24")` | не дольше 14 дней; до `until` падение не блокирует (`xfail`), после — блокирует |

## Фикстуры (SYS-10-R4–R6, R17)

- Тестам с хранилищами (без `no_db` и `n_instances`) хук сбора добавляет `overridden_get_session`,
  `clean_tables` (TRUNCATE таблиц модулей после теста), `redis_clean` (FLUSHDB базы 15 перед тестом)
  и `redis_no_persistent_keys` (после теста — падение на ключе без TTL, без префикса модуля или
  `shared_kernel:`, с TTL сверх максимума категории SYS-05-R13).
- `raw_test_redis` — сырой клиент базы 15 для проверок состояния; `redis_down` — Redis-клиент
  процесса на закрытом порту (поведение без Redis).
- `frozen_clock` — остановленный `Clock` (`set("2026-10-10T12:00:00Z")`, `advance(timedelta(...))`);
  `freezegun` и `sleep` в тестах не используются.
- `eventually` — `await eventually(probe, timeout=2.0)` вместо фиксированных пауз.
- `jwt_signing_keys` — одноразовая Ed25519-пара тестовой сессии: корневой `conftest.py` генерирует
  её до импорта приложения и выставляет `JWT_SIGNING_KEYS`, `JWT_ACTIVE_KID`, `JWT_PUBLIC_KEYS`.

## Детерминизм (SYS-10-R37)

`addopts` в `pyproject.toml`: pytest-socket (`--disable-socket --allow-hosts=127.0.0.1,::1,localhost`) —
сеть только к loopback; pytest-randomly с фиксированным seed `20261010` (порядковые зависимости ищутся
другим seed: `-p randomly --randomly-seed=<n>`); `TZ=UTC` в `envs/.test.env`. Фабрики — `polyfactory`,
заглушки HTTP внешних сервисов — `respx`.

## Стенд из N инстансов (SYS-05-R44–R54)

Тесты `tests/n_instances/` идут через HAProxy стенда из 3 инстансов роли `api` (`--stand-url`):

```shell
make test-n3       # поднять стенд, pytest -m n_instances --stand-url http://127.0.0.1:8080, погасить стенд
make stand-up      # только поднять стенд (docker compose -p flt … --profile ci up -d --wait --scale api=3)
make stand-test    # тесты на поднятом стенде
make stand-down    # погасить стенд
```

Проект compose — `flt` (контейнеры `flt-api-1…3`, `flt-worker-1…2`): стенд заменяет контейнеры
`make compose-up` того же проекта, данные стенда local не трогает (PostgreSQL стенда — на tmpfs).
Параллельно с локальной инфраструктурой — `make test-n3 STAND_PROJECT=flt-n3`. Если ghcr.io недоступен
из сети сборки, образ сборочной стадии подменяется `FLT_UV_IMAGE=<образ с Python 3.14 и uv>`.

Фикстуры (`tests/n_instances/conftest.py`, SYS-05-R46): `stand` (адрес HAProxy, проект compose,
состояние серверов в `stats;csv`), `stand_client`, `instances` (`X-Instance-Id` и прямой адрес каждого
инстанса), `on_instance(n)`, `stop_instance("flt-api-2")`, `pause_instance("flt-api-3")`; teardown
возвращает контейнер и ждёт его состояния UP в HAProxy.

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
