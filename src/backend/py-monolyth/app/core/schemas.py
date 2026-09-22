"""Общие схемы ошибок HTTP-слоя.

Живут в `core`, чтобы и `api`, и `brokers` могли зависеть от них,
не нарушая направление импортов (core ни от кого не зависит).
"""

from typing import Any

from pydantic import BaseModel, Field


class ErrorMessageSchema(BaseModel):
    """Сообщение, что отправляем при ошибке."""

    message_mnemo_code: str = Field(
        description="Мнемокод ошибки (стабильный идентификатор для клиента).",
    )
    parameters: dict[str, Any] = Field(
        description="Параметры ошибки (контекст для отображения/диагностики).",
    )


class InternalServerErrorMessageSchema(BaseModel):
    """Сообщение, что отправляем при 500 ошибке в Debug Mode."""

    log_message: list[str] = Field(
        default_factory=list,
        description="Displayed error message.",
    )
    traceback: list[str] = Field(
        default_factory=list,
        description="Error traceback.",
    )
