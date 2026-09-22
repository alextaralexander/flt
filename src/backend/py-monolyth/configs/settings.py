"""Основные настройки сервиса.

Значения читаются (в порядке приоритета): переменные окружения → env-файл
стенда (`envs/<stand>/<stand>.env`, стенд выбирает `STAND_NAME`) → Vault
(для секретов, см. `configs.vault_config`).
"""

from functools import partial

from dotenv import load_dotenv
from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from configs.stands import DEFAULT_STAND_NAME, stand_env_file
from configs.vault_config import vault_secret, vault_secret_or


load_dotenv(".env")


class Settings(BaseSettings):
    """Настройки приложения (env → env-файл стенда → Vault)."""

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=stand_env_file(),
    )

    # Main
    STAND_NAME: str = Field(
        default=DEFAULT_STAND_NAME,
        description="Имя стенда (окружения); определяет, какой env-файл стенда и секреты Vault использовать.",
    )
    DEBUG_MODE: bool = Field(
        default=False,
        description="Режим отладки; включается явно на local/dev, на проде выключен из соображений безопасности.",
    )
    MIGRATE_ON_START: bool = Field(
        default=True,
        description="Запускать миграции БД при старте; выключай в многорепличном деплое (миграции — отдельный job).",
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

    # Auth (JWT проверяется локально, внешний сервис авторизации не нужен)
    JWT_SECRET_KEY: str = Field(
        default_factory=partial(vault_secret, "JWT_SECRET_KEY"),
        description="Ключ проверки подписи JWT: секрет для HS* или публичный PEM для RS*/ES* (по умолчанию из Vault).",
    )
    JWT_ALGORITHM: str = Field(
        default="HS256",
        description="Единственный разрешённый алгоритм подписи JWT.",
    )
    JWT_ISSUER: str = Field(
        default="",
        description="Ожидаемое значение claim `iss`; пустая строка — не проверять.",
    )
    JWT_ROLE_PERMISSIONS: dict[str, list[str]] = Field(
        default_factory=dict,
        description='Маппинг «роль из claim ROLES → permissions», JSON: {"ADMIN": ["GET_MY_ENTITY", ...]}.',
    )

    # PostgresDatabaseAccess
    PG_HOST: str = Field(
        description="Хост Postgres.",
    )
    PG_PORT: int = Field(
        description="Порт Postgres.",
    )
    PG_DATABASE: str = Field(
        description="Имя базы данных Postgres.",
    )
    PG_SCHEMA: str = Field(
        description="Схема Postgres, используемая сервисом.",
    )
    PG_DRIVER: str = Field(
        description="Драйвер подключения к Postgres (например, asyncpg).",
    )
    PG_USERNAME: str = Field(
        default_factory=partial(vault_secret, "PG_USERNAME"),
        description="Имя пользователя Postgres (по умолчанию читается из Vault).",
    )
    PG_PASSWORD: str = Field(
        default_factory=partial(vault_secret, "PG_PASSWORD"),
        description="Пароль пользователя Postgres (по умолчанию читается из Vault).",
    )

    # Redis
    REDIS_HOST: str = Field(
        description="Хост Redis.",
    )
    REDIS_PORT: int = Field(
        description="Порт Redis.",
    )
    REDIS_DB: int = Field(
        description="Номер базы данных Redis.",
    )

    # Database Engine Settings
    POOL_RECYCLE: int = Field(
        description="Время жизни соединения в пуле SQLAlchemy (в секундах).",
    )
    POOL_TIMEOUT: int = Field(
        description="Максимальное время ожидания получения нового соединения из пула.",
    )
    POOL_SIZE: int = Field(
        description="Максимальное количество соединений в пуле.",
    )
    POOL_MAX_OVERFLOW: int = Field(
        description="Максимальное количество соединений сверх POOL_SIZE.",
    )
    POOL_PRE_PING: bool = Field(
        description="Проверять работоспособность соединения перед использованием.",
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

    ROOT_PATH: str = Field(
        default="",
        description="Префикс пути монтирования приложения (root_path) за обратным прокси.",
    )

    # Opentelemetry
    OTLP_EXPORTER_ENDPOINT: str = Field(
        default="",
        description="Endpoint OTLP-экспортёра трасс и метрик OpenTelemetry.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_database_uri(self) -> str:
        """DSN подключения к Postgres; URL.create экранирует спецсимволы в пароле."""
        return URL.create(
            drivername=f"postgresql+{self.PG_DRIVER}",
            username=self.PG_USERNAME,
            password=self.PG_PASSWORD,
            host=self.PG_HOST,
            port=self.PG_PORT,
            database=self.PG_DATABASE,
        ).render_as_string(hide_password=False)

    OPEN_SEARCH_URL: str = Field(
        default="",
        description="URL OpenSearch для отправки логов.",
    )
    OPEN_SEARCH_LOGS_ENABLED: bool = Field(
        default=False,
        description="Включить отправку логов в OpenSearch.",
    )
    OPEN_SEARCH_VERIFY_SSL: bool = Field(
        default=True,
        description="Проверять SSL-сертификат при подключении к OpenSearch.",
    )
    OPEN_SEARCH_USER_NAME: str = Field(
        default_factory=partial(vault_secret_or, "OPEN_SEARCH_USER_NAME", ""),
        description="Имя пользователя OpenSearch (по умолчанию читается из Vault).",
    )
    OPEN_SEARCH_PASSWORD: str = Field(
        default_factory=partial(vault_secret_or, "OPEN_SEARCH_PASSWORD", ""),
        description="Пароль пользователя OpenSearch (по умолчанию читается из Vault).",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def open_search_index(self) -> str:
        """Имя OpenSearch-индекса логов текущего стенда."""
        return f"{self.STAND_NAME}.flt"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def open_search_service_name(self) -> str:
        """Значение поля `service_name` в записях логов OpenSearch."""
        return f"{self.STAND_NAME}.python_boilerplate"


settings = Settings()
