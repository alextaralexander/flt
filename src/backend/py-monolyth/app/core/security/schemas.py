"""Pydantic-схемы аутентификации (ADR-006, раздел 3.2; SYS-06)."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.security.permissions import Grant, UserFlags


class UserSecuritySchema(BaseModel):
    """Аутентифицированный пользователь запроса или соединения WebSocket.

    Поля `user_id`, `sid`, `roles`, `client`, `email_verified`, `age_confirmed` — из access JWT
    (ADR-006, раздел 3.2); `permissions` — гранты, которые провайдер ролей вывел для запроса
    (SYS-06-R4), уже привязанные к пользователю. Сам токен в схеме не хранится.
    """

    model_config = ConfigDict(frozen=True)

    user_id: UUID = Field(description="ID пользователя (`sub`).")
    sid: UUID = Field(description="ID сессии — семейства refresh-токенов (`sid`).")
    roles: tuple[str, ...] = Field(default=(), description="Роли пользователя: learner, teacher, platform_admin.")
    permissions: frozenset[Grant] = Field(default=frozenset(), description="Гранты запроса (код и область).")
    client: str = Field(default="web", description="Тип клиента: web или mobile.")
    email_verified: bool = Field(default=False, description="Email подтверждён.")
    age_confirmed: bool = Field(default=False, description="Подтверждён возраст 18+ (OQ-14).")

    @property
    def flags(self) -> UserFlags:
        """Признаки пользователя для `RolePermissionsProvider`."""
        return UserFlags(
            user_id=self.user_id,
            sid=self.sid,
            email_verified=self.email_verified,
            age_confirmed=self.age_confirmed,
            client=self.client,
        )

    def grant(self, code: str) -> Grant | None:
        """Грант права `code`, привязанный к пользователю, или None, если права нет."""
        return next((grant for grant in self.permissions if grant.code == code), None)

    def has_permission(self, code: str) -> bool:
        """Есть ли у пользователя право `code` (с любой областью)."""
        return self.grant(code) is not None
