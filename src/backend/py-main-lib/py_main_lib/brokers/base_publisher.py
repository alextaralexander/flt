"""Базовый класс для паблишеров."""

from abc import ABC, abstractmethod
from typing import Any


class BasePublisher(ABC):
    """Абстрактный класс издателя."""

    @abstractmethod
    async def publish(self, *args, **kwargs) -> Any:
        """Абстрактный метод публикации сообщений."""
        pass
