"""Kafka broker logger."""

import structlog


kafka_logger = structlog.stdlib.get_logger("kafka")
