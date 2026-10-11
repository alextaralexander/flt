"""Kafka shared kernel: брокер процесса, middleware, базовые схемы сообщений (ADR-004).

Модули публикуют события только через outbox (этап 1 Г.4) и не импортируют брокер
напрямую (контракт import-linter `kafka-publish-only-via-outbox`).
"""
