"""Enums для Kafka."""

from enum import StrEnum


class KafkaPublisherTopics(StrEnum):
    """Kafka Publisher Topics."""

    INF_TOPIC_01 = "some_service.inf.first_topic.01"
    INF_TOPIC_01_CALLBACK = "some_service.inf.second_topic.01.callback"
    ...  # Добавляем остальные Topics


class KafkaSubscriberTopics(StrEnum):
    """Kafka Subscriber Topics."""

    INF_TOPIC_02 = "some_service.inf.second_topic.02"
    INF_TOPIC_02_CALLBACK = "some_service.inf.second_topic.02.callback"

    INF_TOPIC_03 = "some_service.inf.second_topic.03"
    ...  # Добавляем остальные Topics
