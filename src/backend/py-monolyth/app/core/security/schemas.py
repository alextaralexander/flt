"""Pydantic-схемы аутентификации."""

from pydantic import BaseModel, Field


class UserSecuritySchema(BaseModel):
    """Расширенная схема пользователя, прошедшего аутентификацию."""

    user_id: str = Field(
        description="ID пользователя в UUID формате.",
    )
    permissions: set[str] = Field(
        description="Набор прав пользователя.",
    )
    access_token: str = Field(
        description="JWT токен пользователя.",
    )
