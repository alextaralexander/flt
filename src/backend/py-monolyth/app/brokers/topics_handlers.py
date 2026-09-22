"""Маршрутизация ошибок обработки: входящий Kafka-топик → callback-топик ошибки.

Новый консьюмер с callback-ом добавляется одной строкой в маппинг.
Публикацию выполняет `app.brokers.kafka.middlewares.exception_middleware`
через брокер роутера (он уже подключён в работающем приложении и
подменяется `TestKafkaBroker` в тестах).
"""

from app.brokers.kafka.schemas.enums import KafkaSubscriberTopics


KAFKA_ERROR_TOPIC_BY_SOURCE: dict[str, str] = {
    KafkaSubscriberTopics.INF_TOPIC_02: KafkaSubscriberTopics.INF_TOPIC_02_CALLBACK,
}
