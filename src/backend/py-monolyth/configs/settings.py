"""Основные настройки процесса (shared kernel, раздел 8 спецификации `shared_kernel`).

Значения читаются (в порядке приоритета): переменные окружения → env-файл стенда
(`envs/<stand>/<stand>.env`, стенд выбирает `STAND_NAME`). Секреты — поля `SecretStr`
без значения по умолчанию: они приходят только из переменных окружения (`.env` в
docker-compose, Kubernetes Secret из Vault через External Secrets Operator — ADR-013),
отсутствие секрета останавливает старт. Исключение — стенд local: его env-файл
содержит тестовые значения, помеченные `# pragma: allowlist secret`.
"""

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from configs.stands import DEFAULT_STAND_NAME, stand_env_file


load_dotenv(".env")


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

    # OpenTelemetry: экспорт трейсов выключен до этапа 4 (ADR-010, OQ-20).
    OTLP_EXPORTER_ENDPOINT: str = Field(
        default="",
        description="Endpoint OTLP-экспортёра трейсов; пусто — экспорт выключен.",
    )

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
