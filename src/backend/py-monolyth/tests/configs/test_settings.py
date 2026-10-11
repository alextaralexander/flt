"""Тесты настроек процесса: секреты только из окружения, без Vault и стабов (ADR-013, ADR-003)."""

from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from configs.kafka_config import KafkaSettings
from configs.redis_config import RedisMode, RedisSettings
from configs.settings import AppRole, Settings


pytestmark = pytest.mark.no_db

REQUIRED_ENV = {
    "FAST_API_HOST": "0.0.0.0",  # nosec B104 — значение настройки в тесте, сокет не открывается
    "FAST_API_PORT": "8000",
    "PG_HOST": "postgres",
    "PG_PORT": "5432",
    "PG_DATABASE": "flt",
    "PG_USERNAME": "flt",
    "PG_PASSWORD": "pg-secret-value",  # pragma: allowlist secret
    "AUTH_CSRF_SECRET": "csrf-secret-value",  # pragma: allowlist secret
    "ALLOW_ORIGINS": "[]",
    "ALLOW_CREDENTIALS": "true",
    "ALLOW_METHODS": '["*"]',
    "ALLOW_HEADERS": '["*"]',
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Окружение без настроек процесса: значения задаёт сам тест."""
    for name in (
        *REQUIRED_ENV,
        "REDIS_PASSWORD",
        "REDIS_MODE",
        "REDIS_SENTINEL_HOSTS",
        "STAND_NAME",
        "APP_ROLE",
        "JWT_PUBLIC_KEYS",
    ):
        monkeypatch.delenv(name, raising=False)
    yield monkeypatch


class TestSettingsSecrets:
    """Секреты — `SecretStr` без значения по умолчанию (Arrange / Act / Assert)."""

    @pytest.mark.parametrize("secret", ["PG_PASSWORD", "AUTH_CSRF_SECRET"])
    def test_missing_secret_stops_start(self, clean_env: pytest.MonkeyPatch, secret: str) -> None:
        """Без секрета настройки не создаются: инстанс не стартует с пустым паролем."""
        # - Arrange -
        for name, value in REQUIRED_ENV.items():
            if name != secret:
                clean_env.setenv(name, value)

        # - Act / Assert -
        with pytest.raises(ValidationError, match=secret):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_secrets_are_not_exposed(self, clean_env: pytest.MonkeyPatch) -> None:
        """`repr` и `model_dump` не раскрывают пароль БД и ключ CSRF; DSN содержит пароль."""
        # - Arrange -
        for name, value in REQUIRED_ENV.items():
            clean_env.setenv(name, value)

        # - Act -
        settings = Settings(_env_file=None)  # type: ignore[call-arg]

        # - Assert -
        dumped = repr(settings) + str(settings.model_dump())
        assert "pg-secret-value" not in dumped
        assert "csrf-secret-value" not in dumped
        assert "pg-secret-value" in settings.sqlalchemy_database_uri
        assert settings.OTLP_EXPORTER_ENDPOINT == ""
        assert (settings.JWT_ISSUER, settings.JWT_AUDIENCE, settings.JWT_PUBLIC_KEYS) == ("flt", "flt-api", "")

    def test_removed_boilerplate_settings_are_gone(self) -> None:
        """Vault, JWT boilerplate, OpenSearch-sink и PG_SCHEMA удалены из настроек (ADR-010, ADR-013)."""
        # - Act -
        fields = set(Settings.model_fields)

        # - Assert -
        removed = {"JWT_SECRET_KEY", "JWT_ROLE_PERMISSIONS", "PG_SCHEMA", "OPEN_SEARCH_URL", "ROOT_PATH"}
        assert not fields & removed
        # Миграции при старте инстанса запрещены — настройки нет (SYS-05, ADR-004).
        assert "MIGRATE_ON_START" not in fields
        assert not {"KAFKA_USERNAME", "KAFKA_PASSWORD", "KAFKA_GROUP_ID"} & set(KafkaSettings.model_fields)


class TestAppRole:
    """Роль запуска: `all` по умолчанию только на local (ADR-004, раздел 3.5)."""

    def test_local_defaults_to_all(self, clean_env: pytest.MonkeyPatch) -> None:
        """На стенде local без APP_ROLE процесс работает в роли `all`."""
        # - Arrange -
        for name, value in REQUIRED_ENV.items():
            clean_env.setenv(name, value)

        # - Act -
        settings = Settings(_env_file=None)  # type: ignore[call-arg]

        # - Assert -
        assert settings.role is AppRole.ALL
        assert settings.WORKER_HTTP_PORT == 8001

    def test_role_is_required_outside_local(self, clean_env: pytest.MonkeyPatch) -> None:
        """Вне local APP_ROLE обязательна."""
        # - Arrange -
        for name, value in REQUIRED_ENV.items():
            clean_env.setenv(name, value)
        clean_env.setenv("STAND_NAME", "prod")

        # - Act / Assert -
        with pytest.raises(ValidationError, match="APP_ROLE"):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_explicit_role_is_kept(self, clean_env: pytest.MonkeyPatch) -> None:
        """Явно заданная роль принимается на любом стенде; неизвестная — ошибка."""
        # - Arrange -
        for name, value in REQUIRED_ENV.items():
            clean_env.setenv(name, value)
        clean_env.setenv("STAND_NAME", "prod")
        clean_env.setenv("APP_ROLE", "worker")

        # - Act -
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        clean_env.setenv("APP_ROLE", "scheduler")

        # - Assert -
        assert settings.role is AppRole.WORKER
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_kafka_client_id_contains_role_and_instance(self, clean_env: pytest.MonkeyPatch) -> None:
        """client_id Kafka — `flt-<role>-<instance_id>`."""
        # - Arrange -
        clean_env.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
        clean_env.setenv("HOSTNAME", "flt-worker-1")

        # - Act -
        client_id = KafkaSettings(_env_file=None).client_id("worker")  # type: ignore[call-arg]

        # - Assert -
        assert client_id == "flt-worker-flt-worker-1"


class TestRedisSettings:
    """Режимы Redis и обязательность пароля вне local (ADR-003, ADR-013)."""

    def test_password_is_optional_on_local(self, clean_env: pytest.MonkeyPatch) -> None:
        """На стенде local пустой пароль допустим (локальный контейнер без requirepass)."""
        # - Act -
        settings = RedisSettings(_env_file=None)  # type: ignore[call-arg]

        # - Assert -
        assert settings.REDIS_MODE is RedisMode.STANDALONE
        assert settings.REDIS_PASSWORD.get_secret_value() == ""

    def test_password_is_required_outside_local(self, clean_env: pytest.MonkeyPatch) -> None:
        """Вне local отсутствие REDIS_PASSWORD — ошибка старта."""
        # - Arrange -
        clean_env.setenv("STAND_NAME", "prod")

        # - Act / Assert -
        with pytest.raises(ValidationError, match="REDIS_PASSWORD"):
            RedisSettings(_env_file=None)  # type: ignore[call-arg]

    def test_sentinel_hosts_are_parsed(self, clean_env: pytest.MonkeyPatch) -> None:
        """Адреса Sentinel разбираются в пары (host, port), порт по умолчанию 26379."""
        # - Arrange -
        clean_env.setenv("REDIS_MODE", "sentinel")
        clean_env.setenv("REDIS_SENTINEL_HOSTS", "sentinel-0:26380, sentinel-1")

        # - Act -
        settings = RedisSettings(_env_file=None)  # type: ignore[call-arg]

        # - Assert -
        assert settings.sentinel_hosts == [("sentinel-0", 26380), ("sentinel-1", 26379)]
        assert settings.REDIS_SENTINEL_MASTER == "flt"

    def test_sentinel_mode_requires_hosts(self, clean_env: pytest.MonkeyPatch) -> None:
        """Режим sentinel без адресов Sentinel не принимается."""
        # - Arrange -
        clean_env.setenv("REDIS_MODE", "sentinel")

        # - Act / Assert -
        with pytest.raises(ValidationError, match="REDIS_SENTINEL_HOSTS"):
            RedisSettings(_env_file=None)  # type: ignore[call-arg]
