from pydantic import Field, computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Logging
    LOG_JSON_FORMAT: bool = False
    LOG_LEVEL: str = "INFO"

    # PostgresDatabaseAccess
    PG_HOST: str = "localhost"
    PG_PORT: int = 5432
    PG_DATABASE: str = "flt"
    PG_SCHEMA: str = "ms_py_test"
    PG_DRIVER: str = "asyncpg"
    PG_USERNAME: str = "ms_py_test"
    PG_PASSWORD: str = "ms_py_test"

    # Database Engine Settings
    # POOL_RECYCLE: int  # Время жизни соединения
    # POOL_TIMEOUT: int  # Максимальное время ожидания получения нового соединения
    # POOL_SIZE: int  # Максимальное количество соединений в пуле
    # POOL_MAX_OVERFLOW: int  # Максимальное количество соединений сверх POOL_SIZE
    # POOL_PRE_PING: bool  # Проверять соединение перед использованием

    # Redis
    # REDIS_HOST: str = "127.0.0.1"
    # REDIS_PORT: int = 6379
    # REDIS_DB: int = 0
    # REDIS_DECODE_RESPONSES: bool = True

    # ROOT_PATH: str = ""

    @computed_field
    def sqlalchemy_database_uri(self) -> str:
        return (
            f"postgresql+{self.PG_DRIVER}://{self.PG_USERNAME}:"
            f"{self.PG_PASSWORD}@{self.PG_HOST}:{self.PG_PORT}/{self.PG_DATABASE}"
        )

    TEST_MODE: bool = Field(
        default=False,
        description=(
            "Используется в качестве ЗАЩИТЫ от запуска тестов на реальной БД."
            "Данное значение указывается только в .test.env файле."
        ),
    )
    TEST_AUTH_TOKEN: str = Field(
        default="token",
        description="Токен авторизации для тестов.",
    )
    TEST_USER_ID: str = Field(
        default="None",
        description="ID пользователя для тестов.",
    )

    class Config:
        extra = "ignore"


settings = Settings()
