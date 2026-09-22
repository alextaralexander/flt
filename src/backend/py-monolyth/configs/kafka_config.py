"""Настройки Kafka-брокера (стендовые env-файлы + Vault для SASL-кредов)."""

import logging
import os
import socket
from functools import partial
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

from configs.stands import stand_env_file
from configs.vault_config import vault_secret


load_dotenv(".env")

logger = logging.getLogger(__name__)

DEFAULT_KAFKA_MESSAGE_MAX_BYTES = 10 * 1024 * 1024


class KafkaSubscriberConfig(BaseModel):
    """Параметры подписчика, передаваемые в `@kafka_router.subscriber(...)`."""

    group_id: str | None
    auto_offset_reset: str = "earliest"
    max_partition_fetch_bytes: int = DEFAULT_KAFKA_MESSAGE_MAX_BYTES

    def get_subscriber_kwargs(self) -> dict[str, Any]:
        """Kwargs для распаковки в декоратор subscriber-а."""
        return self.model_dump()


class KafkaSettings(BaseSettings):
    """Основные настройки Kafka (SASL-креды — из env или Vault)."""

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=stand_env_file("kafka"),
    )

    KAFKA_BOOTSTRAP_SERVERS: str
    KAFKA_CLIENT_ID: str
    KAFKA_GROUP_ID: str
    KAFKA_AUTO_OFFSET_RESET: str

    KAFKA_USERNAME: str = Field(default_factory=partial(vault_secret, "KAFKA_USERNAME"))
    KAFKA_PASSWORD: str = Field(default_factory=partial(vault_secret, "KAFKA_PASSWORD"))
    KAFKA_SECURITY_PROTOCOL: str
    KAFKA_SASL_MECHANISM: str
    KAFKA_MAX_REQUEST_SIZE: int = DEFAULT_KAFKA_MESSAGE_MAX_BYTES
    KAFKA_MAX_PARTITION_FETCH_BYTES: int = DEFAULT_KAFKA_MESSAGE_MAX_BYTES
    KAFKA_USE_CONSUMER_GROUP: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def kafka_client_id_new(self) -> str:
        """Уникальный client_id: базовый ID + идентификатор реплики."""
        return f"{self.KAFKA_CLIENT_ID}_{self.get_pod_identity()}"

    @staticmethod
    def get_pod_identity() -> str:
        """Идентификатор реплики: HOSTNAME поды или hostname машины (локальный запуск)."""
        return os.getenv("HOSTNAME") or socket.gethostname()

    @property
    def subscriber_config(self) -> KafkaSubscriberConfig:
        """Конфигурация подписчика из значений стенда."""
        return KafkaSubscriberConfig(
            group_id=self._get_group_id(self.KAFKA_GROUP_ID),
            auto_offset_reset=self.KAFKA_AUTO_OFFSET_RESET,
            max_partition_fetch_bytes=self.KAFKA_MAX_PARTITION_FETCH_BYTES,
        )

    def _get_group_id(self, group_id: str) -> str | None:
        """Возвращает group_id, если consumer groups включены."""
        if self.KAFKA_USE_CONSUMER_GROUP:
            return group_id
        return None


class KafkaSettingsStub(KafkaSettings):
    """Резервные настройки Kafka: без SASL-кредов (локальный PLAINTEXT-брокер).

    Отличается от `KafkaSettings` только default-ами кредов — не ходит в Vault.
    """

    KAFKA_USERNAME: str = ""
    KAFKA_PASSWORD: str = ""


kafka_settings: KafkaSettings
try:
    kafka_settings = KafkaSettings()
except (ValidationError, RuntimeError) as exc:
    # Нет SASL-кредов ни в env, ни в Vault — переходим на PLAINTEXT-стаб.
    # Деградация должна быть видимой: на проде такой warning в логах — сигнал
    # о неправильной конфигурации, а не штатный режим.
    logger.warning("Kafka SASL-креды недоступны (%s) — используется KafkaSettingsStub (PLAINTEXT).", exc)
    kafka_settings = KafkaSettingsStub()
