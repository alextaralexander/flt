"""Основные настройки процесса (shared kernel, раздел 8 спецификации `shared_kernel`).

Значения читаются (в порядке приоритета): переменные окружения → env-файл стенда
(`envs/<stand>/<stand>.env`, стенд выбирает `STAND_NAME`). Секреты — поля `SecretStr`
без значения по умолчанию: они приходят только из переменных окружения (`.env` в
docker-compose, Kubernetes Secret из Vault через External Secrets Operator — ADR-013),
отсутствие секрета останавливает старт. Исключение — стенд local: его env-файл
содержит тестовые значения, помеченные `# pragma: allowlist secret`.
"""

from enum import StrEnum
from typing import Self

from dotenv import load_dotenv
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from configs.stands import DEFAULT_STAND_NAME, stand_env_file


load_dotenv(".env")


class AppRole(StrEnum):
    """Роли запуска монолита из одного образа (ADR-004, раздел 3.5)."""

    API = "api"
    WORKER = "worker"
    ALL = "all"
    MIGRATE = "migrate"
    MEDIA_AGENT = "media_agent"


class Settings(BaseSettings):
    """Настройки процесса монолита (env → env-файл стенда)."""

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=stand_env_file(),
    )

    # Main
    STAND_NAME: str = Field(
        default=DEFAULT_STAND_NAME,
        description="Имя стенда (local, dev, test, prod); определяет набор env-файлов стенда.",
    )
    DEBUG_MODE: bool = Field(
        default=False,
        description="Детали ошибок 500 в ответе; включается только на local (ADR-013).",
    )
    APP_ROLE: AppRole | None = Field(
        default=None,
        description="Роль запуска (ADR-004): api, worker, all, migrate, media_agent; по умолчанию all только на local.",
    )
    WORKER_HTTP_PORT: int = Field(
        default=8001,
        description="Служебный HTTP-порт ролей worker и media_agent (/v1/health, /v1/ready, /v1/metrics).",
    )
    FORWARDED_ALLOW_IPS: str = Field(
        default="*",
        description="Кому uvicorn доверяет X-Forwarded-*: порт 8000 доступен только из внутренней сети (ADR-012).",
    )
    SHUTDOWN_GRACE_SECONDS: int = Field(
        default=30,
        description="Время на завершение активных запросов и стримов при остановке инстанса (ADR-009).",
    )

    # Logging
    LOG_JSON_FORMAT: bool = Field(
        default=False,
        description="Выводить логи в JSON-формате (иначе — человекочитаемый текст).",
    )
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Уровень логирования (DEBUG, INFO, WARNING, ERROR, ...).",
    )

    # Mandatory
    FAST_API_HOST: str = Field(
        description="Хост, на котором поднимается FastAPI-приложение.",
    )
    FAST_API_PORT: int = Field(
        description="Порт, на котором поднимается FastAPI-приложение.",
    )

    # Проверка токенов (ADR-006). Ключи подписи JWT_SIGNING_KEYS/JWT_ACTIVE_KID читает модуль
    # identity (этап 1 Г.5); проверку по kid реализует TokenVerifier shared kernel (этап 1 Г.4).
    JWT_PUBLIC_KEYS: str = Field(
        default="",
        description='Публичные ключи проверки JWT по kid, JSON {"<kid>": "<PEM>"}; пусто — из JWT_SIGNING_KEYS.',
    )
    JWT_ISSUER: str = Field(
        default="flt",
        description="Ожидаемое значение claim `iss`.",
    )
    JWT_AUDIENCE: str = Field(
        default="flt-api",
        description="Ожидаемое значение claim `aud`.",
    )
    AUTH_CSRF_SECRET: SecretStr = Field(
        description="Ключ HMAC signed double-submit CSRF-токена (секрет, ADR-006, ADR-013).",
    )

    # PostgreSQL (одна база flt, схема на модуль — ADR-003)
    PG_HOST: str = Field(
        description="Хост Postgres.",
    )
    PG_PORT: int = Field(
        description="Порт Postgres.",
    )
    PG_DATABASE: str = Field(
        description="Имя базы данных Postgres.",
    )
    PG_DRIVER: str = Field(
        default="asyncpg",
        description="Драйвер подключения к Postgres.",
    )
    PG_USERNAME: str = Field(
        description="Имя пользователя Postgres (вне local — из переменных окружения, ADR-013).",
    )
    PG_PASSWORD: SecretStr = Field(
        description="Пароль пользователя Postgres (секрет, ADR-013).",
    )

    # CORS
    ALLOW_ORIGINS: list[str] = Field(
        description="Список доменов, которым разрешён доступ (CORS Allow-Origin).",
    )
    ALLOW_CREDENTIALS: bool = Field(
        description="Разрешить использование куки и авторизации в CORS-запросах.",
    )
    ALLOW_METHODS: list[str] = Field(
        description="Список разрешённых HTTP-методов (CORS Allow-Methods).",
    )
    ALLOW_HEADERS: list[str] = Field(
        description="Список разрешённых HTTP-заголовков (CORS Allow-Headers).",
    )

    # OpenTelemetry: экспорт трейсов выключен до этапа 4 (ADR-010, OQ-20).
    OTLP_EXPORTER_ENDPOINT: str = Field(
        default="",
        description="Endpoint OTLP-экспортёра трейсов; пусто — экспорт выключен.",
    )

    @model_validator(mode="after")
    def _default_role_only_on_local(self) -> Self:
        """Роль по умолчанию (`all`) — только на стенде local; на остальных `APP_ROLE` обязательна (ADR-004)."""
        if self.APP_ROLE is None:
            if self.STAND_NAME != DEFAULT_STAND_NAME:
                raise ValueError("APP_ROLE обязательна на стендах, кроме local: api, worker, migrate, media_agent.")
            self.APP_ROLE = AppRole.ALL
        return self

    @property
    def role(self) -> AppRole:
        """Роль запуска процесса (после валидации всегда задана)."""
        return self.APP_ROLE or AppRole.ALL

    @property
    def sqlalchemy_database_uri(self) -> str:
        """DSN подключения к Postgres; URL.create экранирует спецсимволы в пароле.

        Обычное свойство, а не `computed_field`: DSN с паролем не должен попадать
        в `repr` и `model_dump` настроек.
        """
        return URL.create(
            drivername=f"postgresql+{self.PG_DRIVER}",
            username=self.PG_USERNAME,
            password=self.PG_PASSWORD.get_secret_value(),
            host=self.PG_HOST,
            port=self.PG_PORT,
            database=self.PG_DATABASE,
        ).render_as_string(hide_password=False)


settings = Settings()
