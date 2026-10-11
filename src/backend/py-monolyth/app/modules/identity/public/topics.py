"""Топики Kafka модуля `identity` (SYS-04-R19, R21).

По декларациям роль `migrate` создаёт топики и их DLQ; консьюмеры других модулей импортируют
отсюда декларации публичных топиков. Строки добавляет `make scaffold-subscriber`.
"""

from app.core.kafka.declarations import TopicDeclaration


TOPICS: tuple[TopicDeclaration, ...] = ()
