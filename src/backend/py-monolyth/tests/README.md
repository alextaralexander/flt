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
