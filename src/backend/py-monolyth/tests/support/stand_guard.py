"""Защита от запуска pytest на рабочих данных (SYS-10-R4, решение OQ-31).

pytest работает с отдельной базой PostgreSQL `flt_test` и базой Redis `15` того же экземпляра,
что и стенд local; оверлей `envs/.test.env` задаёт `TEST_MODE=true`, `PG_DATABASE=flt_test`,
`REDIS_DB=15`. Фикстуры, которые меняют схему или очищают данные, сначала вызывают эти проверки.
"""

TEST_DATABASE_SUFFIX = "_test"
TEST_REDIS_DB = 15


def assert_test_database(*, test_mode: bool, database: str) -> None:
    """Разрешает миграции и очистку таблиц только в тестовой базе.

    Args:
        test_mode: Значение `TEST_MODE` (оверлей `envs/.test.env`).
        database: Имя базы PostgreSQL из настроек (`PG_DATABASE`).

    Raises:
        AssertionError: `TEST_MODE` не установлен или имя базы не оканчивается на `_test`.
    """
    if not test_mode:
        raise AssertionError("TEST_MODE не установлен — тесты запущены не на тестовом стенде (SYS-10-R4).")
    if not database.endswith(TEST_DATABASE_SUFFIX):
        raise AssertionError(
            f"PG_DATABASE={database!r}: pytest работает только с базой *{TEST_DATABASE_SUFFIX} (SYS-10-R4)."
        )


def assert_test_redis_db(*, test_mode: bool, db: int) -> None:
    """Разрешает очистку Redis (`FLUSHDB`) только в тестовой базе Redis 15.

    Args:
        test_mode: Значение `TEST_MODE` (оверлей `envs/.test.env`).
        db: Номер базы Redis из настроек (`REDIS_DB`).

    Raises:
        AssertionError: `TEST_MODE` не установлен или база Redis — не 15.
    """
    if not test_mode:
        raise AssertionError("TEST_MODE не установлен — тесты запущены не на тестовом стенде (SYS-10-R4).")
    if db != TEST_REDIS_DB:
        raise AssertionError(f"REDIS_DB={db}: pytest очищает только базу Redis {TEST_REDIS_DB} (SYS-10-R4).")
