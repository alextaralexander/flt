"""Модель прав shared kernel: коды прав, области, гранты и интерфейс провайдера ролей (SYS-06).

- Код права — `<module>:<resource>:<action>`, действие — из закрытого перечня `PERMISSION_ACTIONS`
  (SYS-06-R2); коды объявляют модули в `permissions.py` и `ModuleDefinition.permissions`.
- Грант (`Grant`) — право с областью `own`, `rel` или `any` для текущего запроса; объектную
  проверку выполняет `Grant.ensure` (SYS-06-R6).
- Права выводятся из ролей при каждой проверке через `RolePermissionsProvider` (SYS-06-R4):
  интерфейс объявлен здесь, реализацию регистрирует модуль `identity` в
  `ModuleDefinition.role_permissions_provider` (ADR-006, раздел 3.8). Пока провайдера нет,
  действует `DenyAllPermissionsProvider` — прав нет ни у кого (fail-closed).
"""

import inspect
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, Self, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.security.errors import ForbiddenError


# SYS-06-R2: закрытый перечень действий; новое действие добавляется правкой требования.
PERMISSION_ACTIONS: frozenset[str] = frozenset(
    {
        "read",
        "create",
        "update",
        "delete",
        "publish",
        "unpublish",
        "start",
        "send",
        "invite",
        "join",
        "leave",
        "grant",
        "revoke",
        "suspend",
        "restrict",
        "moderate",
        "export",
        "use",
        "manage",
        "accept",
        "adjust",
        "approve",
        "archive",
        "claim",
        "confirm",
        "decide",
        "decline",
        "disable",
        "download",
        "enable",
        "finish",
        "hide",
        "install",
        "invite_tutor",
        "lift_restriction",
        "login",
        "logout",
        "logout_all",
        "mute",
        "poll",
        "read_any",
        "read_course_content",
        "read_draft",
        "read_public",
        "refresh",
        "regenerate",
        "register",
        "reject",
        "remove",
        "resolve",
        "restore",
        "search",
        "select",
        "test",
        "unhide",
        "uninstall",
        "unsuspend",
    }
)

PERMISSION_CODE_RE = re.compile(r"^[a-z_]+:[a-z_]+:[a-z_]+$")


def validate_permission_code(code: str) -> str:
    """Проверяет код права по SYS-06-R2 и возвращает его без изменений.

    Args:
        code: Код вида `<module>:<resource>:<action>`.

    Returns:
        Тот же код.

    Raises:
        ValueError: Формат не совпадает с `^[a-z_]+:[a-z_]+:[a-z_]+$` или действия нет в `PERMISSION_ACTIONS`.
    """
    if not PERMISSION_CODE_RE.match(code):
        raise ValueError(f"Код права {code!r} не по формату <module>:<resource>:<action> (SYS-06-R2).")
    action = code.rsplit(":", 1)[1]
    if action not in PERMISSION_ACTIONS:
        raise ValueError(f"Действие {action!r} кода {code!r} нет в PERMISSION_ACTIONS (SYS-06-R2).")
    return code


class Scope(StrEnum):
    """Область права (SYS-06, раздел 2): свои объекты, свои и связанных пользователей, все."""

    OWN = "own"
    REL = "rel"
    ANY = "any"


class Permission(BaseModel):
    """Право `<module>:<resource>:<action>` (SYS-06-R2) — проверенный код с разбором на сегменты."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(description="Код права `<module>:<resource>:<action>`.")

    @field_validator("code")
    @classmethod
    def _check_code(cls, value: str) -> str:
        """Код права — по формату SYS-06-R2."""
        return validate_permission_code(value)

    @property
    def module(self) -> str:
        """Модуль-владелец права (первый сегмент)."""
        return self.code.split(":")[0]

    @property
    def resource(self) -> str:
        """Ресурс права (второй сегмент, множественное число)."""
        return self.code.split(":")[1]

    @property
    def action(self) -> str:
        """Действие права из `PERMISSION_ACTIONS` (третий сегмент)."""
        return self.code.split(":")[2]


# Отношение «владелец объекта связан с пользователем» для области `rel` (SYS-01-R17); sync или async.
Relation = Callable[[], bool | Awaitable[bool]]


class Grant(BaseModel):
    """Грант запроса: код права и максимальная область среди ролей пользователя (SYS-06, раздел 2).

    Провайдер ролей возвращает гранты без пользователя; `auth_user` привязывает их к
    аутентифицированному пользователю (`bind`), после чего `ensure` проверяет объекты.
    В ответ API (`GET /me`, SYS-06-R9) попадают только `code` и `scope`.
    """

    model_config = ConfigDict(frozen=True)

    code: str = Field(description="Код права `<module>:<resource>:<action>`.")
    scope: Scope = Field(description="Область: own, rel или any.")
    user_id: UUID | None = Field(default=None, exclude=True, description="Пользователь, которому выдан грант.")

    @field_validator("code")
    @classmethod
    def _check_code(cls, value: str) -> str:
        """Код права — по формату SYS-06-R2."""
        return validate_permission_code(value)

    def bind(self, user_id: UUID) -> Grant:
        """Копия гранта, привязанная к пользователю запроса."""
        return self.model_copy(update={"user_id": user_id})

    async def ensure(self, owner_id: UUID | None, relation: Relation | None = None) -> None:
        """Проверяет, что объект с владельцем `owner_id` входит в область гранта (SYS-06-R6).

        - `any` — любой объект;
        - `own` — только `owner_id == user_id`;
        - `rel` — свой объект или `relation()` вернул True (связь по SYS-01-R17).

        Args:
            owner_id: Владелец объекта (`owner_user_id`); None — у объекта нет владельца.
            relation: Проверка связи владельца с пользователем для области `rel`.

        Raises:
            ForbiddenError: Объект вне области (`core.forbidden`); выбор 403 или 404 для
                скрываемых ресурсов делает сервис модуля (SYS-06-R6).
            RuntimeError: Грант не привязан к пользователю (`bind`) — ошибка программиста.
        """
        if self.scope is Scope.ANY:
            return
        if self.user_id is None:
            raise RuntimeError("Грант не привязан к пользователю: используйте грант из auth_user (bind).")
        if owner_id is not None and owner_id == self.user_id:
            return
        if self.scope is Scope.REL and relation is not None and owner_id is not None:
            related = relation()
            if inspect.isawaitable(related):
                related = await related
            if related:
                return
        raise ForbiddenError()


@dataclass(frozen=True)
class UserFlags:
    """Признаки пользователя из access-токена, нужные провайдеру ролей (ADR-006, раздел 3.2; SYS-06-R7).

    Согласие `personal_data` и активные ограничения в токене не передаются — провайдер `identity`
    читает их сам по `user_id`.
    """

    user_id: UUID | None
    sid: UUID | None
    email_verified: bool
    age_confirmed: bool
    client: str | None = None

    @classmethod
    def anonymous(cls) -> Self:
        """Флаги анонимного запроса: без пользователя, сессии и подтверждений."""
        return cls(user_id=None, sid=None, email_verified=False, age_confirmed=False)


@runtime_checkable
class RolePermissionsProvider(Protocol):
    """Вывод грантов из ролей по матрице SYS-06 (ADR-006, раздел 3.8; SYS-06-R4).

    Реализует модуль `identity` и регистрирует её в `ModuleDefinition.role_permissions_provider`.
    Методы асинхронные: провайдер учитывает согласие `personal_data` и ограничения пользователя,
    которых нет в токене. Результат не кэшируется дольше запроса.
    """

    async def grants_for(self, roles: Sequence[str], flags: UserFlags) -> frozenset[Grant]:
        """Гранты пользователя с ролями `roles` (пустые роли — аноним) с учётом подтверждений и санкций."""
        ...

    async def denial_code(self, permission: str, roles: Sequence[str], flags: UserFlags) -> str | None:
        """Код ошибки 403 для права, которого нет в грантах, или None — общий `core.forbidden`.

        Нужен для кодов доступа к обучению: `identity.email_not_verified`, `identity.age_not_confirmed`,
        `identity.consent_required` (SYS-06-R7).
        """
        ...


class DenyAllPermissionsProvider:
    """Провайдер по умолчанию, пока модуль `identity` не подключён: никаких прав (fail-closed)."""

    async def grants_for(self, roles: Sequence[str], flags: UserFlags) -> frozenset[Grant]:
        """Пустое множество грантов для любых ролей."""
        return frozenset()

    async def denial_code(self, permission: str, roles: Sequence[str], flags: UserFlags) -> str | None:
        """Специального кода отказа нет."""
        return None
