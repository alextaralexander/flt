"""Тесты защиты от запуска pytest на рабочих данных (SYS-10-R4, решение OQ-31)."""

import pytest

from configs.redis_config import redis_settings
from configs.settings import settings
from tests.settings import test_settings
from tests.support.stand_guard import assert_test_database, assert_test_redis_db


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-10-R4")]


class TestDatabaseGuard:
    """`db_migrate` и очистка таблиц работают только в базе `*_test` при `TEST_MODE`."""

    def test_refuses_working_database(self) -> None:
        """База стенда local `flt` отклоняется даже при `TEST_MODE`."""
        # - Act / Assert -
        with pytest.raises(AssertionError, match="PG_DATABASE='flt'"):
            assert_test_database(test_mode=True, database="flt")

    def test_refuses_without_test_mode(self) -> None:
        """Без `TEST_MODE` отклоняется и тестовая база."""
        # - Act / Assert -
        with pytest.raises(AssertionError, match="TEST_MODE"):
            assert_test_database(test_mode=False, database="flt_test")

    def test_accepts_test_database(self) -> None:
        """База `flt_test` при `TEST_MODE` разрешена."""
        # - Act / Assert -
        assert_test_database(test_mode=True, database="flt_test")


class TestRedisGuard:
    """Очистка Redis разрешена только в базе 15 при `TEST_MODE`."""

    @pytest.mark.parametrize("db", [0, 1, 14])
    def test_refuses_other_redis_db(self, db: int) -> None:
        """База Redis стенда local (0) и любые другие отклоняются."""
        # - Act / Assert -
        with pytest.raises(AssertionError, match=f"REDIS_DB={db}"):
            assert_test_redis_db(test_mode=True, db=db)

    def test_refuses_without_test_mode(self) -> None:
        """Без `TEST_MODE` отклоняется и база 15."""
        # - Act / Assert -
        with pytest.raises(AssertionError, match="TEST_MODE"):
            assert_test_redis_db(test_mode=False, db=15)


def test_pytest_overlay_points_to_test_storages() -> None:
    """Оверлей `envs/.test.env` направляет pytest в `flt_test` и Redis 15 (SYS-10-R4)."""
    # - Assert -
    assert test_settings.TEST_MODE is True
    assert settings.PG_DATABASE == "flt_test"
    assert redis_settings.REDIS_DB == 15
