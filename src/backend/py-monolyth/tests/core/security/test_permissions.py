"""Тесты модели прав shared kernel: коды, области, гранты (SYS-06-R2, R4, R6)."""

from uuid import UUID, uuid4

import pytest

from app.core.security.errors import ForbiddenError
from app.core.security.permissions import (
    PERMISSION_ACTIONS,
    DenyAllPermissionsProvider,
    Grant,
    Permission,
    RolePermissionsProvider,
    Scope,
    UserFlags,
    validate_permission_code,
)


pytestmark = pytest.mark.no_db

USER = UUID("00000000-0000-7000-8000-000000000001")
OTHER = UUID("00000000-0000-7000-8000-000000000002")


@pytest.mark.req("SYS-06-R2")
class TestPermissionCode:
    """Код права `<module>:<resource>:<action>` с действием из закрытого перечня."""

    @pytest.mark.parametrize("code", ["identity:me:read", "learning_plan:plans:adjust", "social:content:unhide"])
    def test_valid_codes_are_accepted(self, code: str) -> None:
        """Коды из матрицы SYS-06 проходят проверку и разбираются на сегменты."""
        # - Act -
        permission = Permission(code=code)

        # - Assert -
        assert validate_permission_code(code) == code
        assert f"{permission.module}:{permission.resource}:{permission.action}" == code

    @pytest.mark.parametrize(
        "code",
        ["IDENTITY_GET_USER", "identity:me", "identity:me:read:any", "identity:Me:read", "identity:me:fly", ""],
    )
    def test_invalid_codes_are_rejected(self, code: str) -> None:
        """Неверный формат или действие вне `PERMISSION_ACTIONS` — `ValueError`."""
        # - Act / Assert -
        with pytest.raises(ValueError, match="SYS-06-R2"):
            validate_permission_code(code)

    def test_actions_list_is_closed(self) -> None:
        """Перечень действий содержит базовые и специальные действия SYS-06-R2 и неизменяем."""
        # - Assert -
        assert {"read", "manage", "read_public", "unsuspend", "invite_tutor"} <= PERMISSION_ACTIONS
        assert isinstance(PERMISSION_ACTIONS, frozenset)


@pytest.mark.req("SYS-06-R6")
class TestGrantEnsure:
    """Объектная проверка гранта по области `own`, `rel`, `any`."""

    async def test_own_allows_only_owner(self) -> None:
        """`own`: свой объект — разрешено, чужой — `ForbiddenError` (`core.forbidden`)."""
        # - Arrange -
        grant = Grant(code="learning_plan:plans:read", scope=Scope.OWN).bind(USER)

        # - Act / Assert -
        await grant.ensure(owner_id=USER)
        with pytest.raises(ForbiddenError) as exc_info:
            await grant.ensure(owner_id=OTHER)
        assert exc_info.value.error_code == "core.forbidden"

    async def test_rel_uses_relation_for_foreign_object(self) -> None:
        """`rel`: свой объект — без вызова отношения; чужой — по результату `relation` (sync и async)."""
        # - Arrange -
        grant = Grant(code="learning_plan:plans:read", scope=Scope.REL).bind(USER)
        calls: list[UUID] = []

        async def related() -> bool:
            calls.append(OTHER)
            return True

        # - Act / Assert -
        await grant.ensure(owner_id=USER, relation=lambda: False)
        await grant.ensure(owner_id=OTHER, relation=related)
        assert calls == [OTHER]
        with pytest.raises(ForbiddenError):
            await grant.ensure(owner_id=OTHER, relation=lambda: False)
        with pytest.raises(ForbiddenError):
            await grant.ensure(owner_id=OTHER)

    async def test_any_allows_every_object(self) -> None:
        """`any`: доступ к любому объекту, включая объект без владельца."""
        # - Arrange -
        grant = Grant(code="identity:users:read", scope=Scope.ANY).bind(USER)

        # - Act / Assert -
        await grant.ensure(owner_id=OTHER)
        await grant.ensure(owner_id=None)

    async def test_unbound_grant_cannot_check_objects(self) -> None:
        """Грант без пользователя (не из `auth_user`) не подтверждает владение — ошибка программиста."""
        # - Arrange -
        grant = Grant(code="learning_plan:plans:read", scope=Scope.OWN)

        # - Act / Assert -
        with pytest.raises(RuntimeError, match="bind"):
            await grant.ensure(owner_id=USER)

    def test_serialization_has_only_code_and_scope(self) -> None:
        """В ответ `GET /me` грант попадает как `{code, scope}` (SYS-06-R9), без `user_id`."""
        # - Arrange -
        grant = Grant(code="identity:me:read", scope=Scope.OWN).bind(uuid4())

        # - Act -
        dumped = grant.model_dump(mode="json")

        # - Assert -
        assert dumped == {"code": "identity:me:read", "scope": "own"}

    def test_invalid_code_is_rejected(self) -> None:
        """Грант нельзя создать с кодом не по формату SYS-06-R2."""
        # - Act / Assert -
        with pytest.raises(ValueError, match="SYS-06-R2"):
            Grant(code="IDENTITY_GET_USER", scope=Scope.ANY)


@pytest.mark.req("SYS-06-R4")
class TestDenyAllProvider:
    """Без провайдера ролей (модуль `identity` не подключён) прав нет: fail-closed."""

    async def test_no_grants_and_no_denial_code(self) -> None:
        """Пустое множество грантов для любых ролей; специального кода отказа нет."""
        # - Arrange -
        provider: RolePermissionsProvider = DenyAllPermissionsProvider()
        flags = UserFlags(user_id=USER, sid=uuid4(), email_verified=True, age_confirmed=True, client="web")

        # - Act -
        grants = await provider.grants_for(("learner",), flags)
        denial = await provider.denial_code("identity:me:read", ("learner",), flags)

        # - Assert -
        assert grants == frozenset()
        assert denial is None
        assert isinstance(provider, RolePermissionsProvider)

    def test_anonymous_flags(self) -> None:
        """Флаги анонима: без пользователя, сессии и подтверждений."""
        # - Act -
        flags = UserFlags.anonymous()

        # - Assert -
        assert (flags.user_id, flags.sid, flags.email_verified, flags.age_confirmed) == (None, None, False, False)
