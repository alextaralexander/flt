"""Базовый класс для подписчиков."""

from abc import ABC, abstractmethod
from typing import Any


class BaseSubscriber(ABC):
    @abstractmethod
    async def process(self, message: Any):
        """Абстрактный метод обработки сообщений."""
        pass
