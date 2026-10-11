"""Настройки Kafka-брокера (ADR-004, ADR-013).

Kafka доступна только во внутренней сети (listener PLAINTEXT, без SASL — ADR-013),
поэтому учётных данных нет. Группа консьюмеров не задаётся настройкой: она
вычисляется из модуля и обработчика (`flt.<module>.<handler>`, ADR-004).
"""

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from configs.stands import instance_id, stand_env_file


load_dotenv(".env")

DEFAULT_KAFKA_MESSAGE_MAX_BYTES = 10 * 1024 * 1024


class KafkaSettings(BaseSettings):
    """Основные настройки Kafka (env → `envs/<stand>/kafka_<stand>.env`)."""

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=stand_env_file("kafka"),
    )

    KAFKA_BOOTSTRAP_SERVERS: str = Field(
        description="Адреса брокеров Kafka через запятую.",
    )
    KAFKA_CLIENT_ID: str = Field(
        default="flt",
        description="Префикс client_id; полный client_id дополняется идентификатором инстанса.",
    )
    KAFKA_MAX_REQUEST_SIZE: int = Field(
        default=DEFAULT_KAFKA_MESSAGE_MAX_BYTES,
        description="Максимальный размер публикуемого сообщения, байт.",
    )
    KAFKA_REPLICATION_FACTOR: int = Field(
        default=1,
        ge=1,
        description="replication.factor создаваемых топиков: 1 в docker-compose, 3 в Kubernetes (SYS-04-R23).",
    )

    def client_id(self, role: str) -> str:
        """client_id инстанса: `flt-<role>-<instance_id>` (ADR-004, раздел 3.5)."""
        return f"{self.KAFKA_CLIENT_ID}-{role}-{instance_id()}"


kafka_settings = KafkaSettings()
