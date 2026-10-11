"""Соглашения `ModuleDefinition`: настройки, права, публичный API, REST-префиксы, объявление доступа.

ADR-002 §3.3, §3.6; SYS-03-R1, R2; SYS-05-R22; SYS-06-R2, R5, R18.
"""

import importlib
import shutil
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import APIRouter, Security
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import MetaData

from app.core.modules import ModuleDefinition
from app.core.security.schemas import UserSecuritySchema
from app.core.security.security import auth_user
from app.main import create_app
from tests.architecture import checks
from tests.architecture.conftest import ALLOWED_EXTRA_PREFIXES, IGNORED


pytestmark = pytest.mark.no_db


class _WrongSettings(BaseSettings):
    """Настройки с префиксом чужого модуля."""

    model_config = SettingsConfigDict(env_prefix="IDENTITY_")


def _synthetic_module(name: str = "rogue_mod", **overrides: object) -> ModuleDefinition:
    """Синтетический модуль с переопределёнными полями `ModuleDefinition`."""
    fields: dict[str, object] = {"name": name, "metadata": MetaData(schema=name), **overrides}
    return ModuleDefinition(**fields)


def _router_with_routes() -> APIRouter:
    """Роутер `rogue_mod`: защищённый роут, роут без права, роут вне префикса модуля."""
    router = APIRouter(prefix="/api/v1/rogue-mod")

    @router.get("/items")
    async def protected(
        user: Annotated[UserSecuritySchema, Security(auth_user(permissions_to_check=["rogue_mod:items:read"]))],
    ) -> None:
        """Роут с объявленным правом."""

    @router.get("/open")
    async def unprotected() -> None:
        """Роут без объявления доступа."""

    @router.get("/authenticated-only")
    async def no_permission(user: Annotated[UserSecuritySchema, Security(auth_user())]) -> None:
        """Роут с аутентификацией, но без права."""

    outside = APIRouter(prefix="/api/v1/other")

    @outside.get("/x")
    async def foreign(
        user: Annotated[UserSecuritySchema, Security(auth_user(permissions_to_check=["rogue_mod:items:read"]))],
    ) -> None:
        """Роут чужого префикса, подмешанный в роутер модуля."""

    router.routes.extend(outside.routes)
    return router


@pytest.mark.req("SYS-06-R2")
class TestModuleSettingsPrefix:
    """`env_prefix` настроек модуля равен `<MODULE>_`, у кодов прав — первый сегмент `<module>:`."""

    def test_registry_modules(self, registry_modules: list[ModuleDefinition]) -> None:
        """Модули реестра."""
        assert checks.settings_prefix_violations(registry_modules) == []

    def test_sample_modules(self, sample_report: dict[str, list[str]]) -> None:
        """Модули-образцы скаффолдера (`IDENTITY_`, `LLM_GATEWAY_`)."""
        assert sample_report["settings_prefix"] == []

    def test_wrong_prefix_is_reported(self) -> None:
        """Префикс чужого модуля обнаруживается."""
        module = _synthetic_module(settings=_WrongSettings())

        assert checks.settings_prefix_violations([module]) == [
            "rogue_mod: env_prefix 'IDENTITY_', ожидается ROGUE_MOD_"
        ]


@pytest.mark.req("SYS-06-R2")
class TestPermissionCodesFormat:
    """Коды прав `<module>:<resource>:<action>`: формат, владелец, действие из `PERMISSION_ACTIONS`, уникальность."""

    def test_registry_modules(self, registry_modules: list[ModuleDefinition]) -> None:
        """Модули реестра."""
        assert checks.permission_violations(registry_modules) == []

    def test_sample_modules(self, sample_report: dict[str, list[str]]) -> None:
        """Права сущностей скаффолдера (`identity:users:read` и т.п.)."""
        assert sample_report["permissions"] == []

    def test_bad_codes_are_reported(self) -> None:
        """Чужой модуль, неизвестное действие, неверный формат и дубликат обнаруживаются."""
        first = _synthetic_module(permissions=("rogue_mod:items:read", "identity:users:read", "rogue_mod:items:fly"))
        second = _synthetic_module("other_mod", permissions=("IDENTITY_GET_USER", "rogue_mod:items:read"))

        assert checks.permission_violations([first, second]) == [
            "rogue_mod: код 'identity:users:read' с чужим первым сегментом",
            "rogue_mod: действие 'fly' кода 'rogue_mod:items:fly' нет в PERMISSION_ACTIONS",
            "other_mod: код 'IDENTITY_GET_USER' не по формату <module>:<resource>:<action>",
            "other_mod: код 'rogue_mod:items:read' с чужим первым сегментом",
            "other_mod: код 'rogue_mod:items:read' уже объявлен модулем rogue_mod",
        ]

    def test_permission_actions_match_shared_kernel(self) -> None:
        """Перечень действий теста совпадает с `PERMISSION_ACTIONS` shared kernel (появляется в Г.4)."""
        try:
            permissions = importlib.import_module("app.core.security.permissions")
        except ModuleNotFoundError:
            pytest.skip("app/core/security/permissions.py с PERMISSION_ACTIONS появляется в этапе 1 Г.4 (SYS-06-R2)")
        assert set(permissions.PERMISSION_ACTIONS) == checks.PERMISSION_ACTIONS


@pytest.mark.req("SYS-05-R22")
class TestModulePublicExportsOnlyContracts:
    """`public/` не импортирует модели и DAO, `Protocol` не передаёт сессии и модели через границу."""

    def test_current_tree(self) -> None:
        """Модули текущего дерева."""
        assert checks.public_api_violations(checks.SERVICE_ROOT) == []

    def test_sample_tree(self, sample_tree: Path) -> None:
        """Модули-образцы скаффолдера."""
        assert checks.public_api_violations(sample_tree) == []

    def test_leaks_are_reported(self, sample_tree: Path, tmp_path: Path) -> None:
        """Реэкспорт модели и DAO и `AsyncSession`/модель в `Protocol` обнаруживаются; импорт в фабрике — нет."""
        # - Arrange -
        tree = tmp_path / "service"
        shutil.copytree(sample_tree, tree, ignore=IGNORED)
        (tree / "app" / "modules" / "identity" / "public" / "interfaces.py").write_text(
            '"""Публичный API с утечками."""\n\n'
            "from typing import Protocol\n\n"
            "from sqlalchemy.ext.asyncio import AsyncSession\n\n"
            "from app.modules.identity.dao.user_dao import UserDAO\n"
            "from app.modules.identity.models.user import User\n\n\n"
            "class IdentityService(Protocol):\n"
            '    """Интерфейс."""\n\n'
            "    async def get_user(self, session: AsyncSession) -> 'User':\n"
            '        """Плохо: сессия и модель через границу."""\n'
            "        ...\n\n\n"
            "def get_identity_service() -> IdentityService:\n"
            '    """Фабрика: импорт реализации внутри функции допустим."""\n'
            "    from app.modules.identity.dao.user_dao import UserDAO as Impl\n\n"
            "    return Impl()\n",
            encoding="utf-8",
        )

        # - Act -
        violations = checks.public_api_violations(tree)

        # - Assert -
        rel = "app/modules/identity/public/interfaces.py"
        assert violations == [
            f"{rel}:7: public импортирует app.modules.identity.dao.user_dao.UserDAO",
            f"{rel}:8: public импортирует app.modules.identity.models.user.User",
            f"{rel}:14: IdentityService.get_user использует AsyncSession",
            f"{rel}:14: IdentityService.get_user использует User",
        ]


@pytest.mark.req("SYS-03-R1")
@pytest.mark.req("SYS-03-R2")
class TestRouterPrefixMatchesModule:
    """Пути роутера — под `/api/v1/<module-kebab>/` или разрешённым `extra_prefixes` (только `identity`)."""

    def test_allowed_extra_prefixes(self) -> None:
        """Единственное исключение SYS-03 — `/api/v1/auth` модуля `identity`."""
        assert ALLOWED_EXTRA_PREFIXES == {"identity": ("/api/v1/auth",)}

    def test_registry_modules(self, registry_modules: list[ModuleDefinition]) -> None:
        """Модули реестра."""
        assert checks.router_prefix_violations(registry_modules, ALLOWED_EXTRA_PREFIXES) == []

    def test_sample_modules(self, sample_report: dict[str, list[str]]) -> None:
        """Модули-образцы скаффолдера (`/api/v1/identity`, `/api/v1/llm-gateway`)."""
        assert sample_report["router_prefix"] == []

    def test_wrong_prefixes_are_reported(self) -> None:
        """Путь вне префикса, неразрешённый `extra_prefixes` и чужой префикс роутера обнаруживаются."""
        module = _synthetic_module(router=_router_with_routes(), extra_prefixes=("/api/v1/auth",))
        wrong_prefix = _synthetic_module("other_mod", router=APIRouter(prefix="/api/v1/other_mod"))

        assert checks.router_prefix_violations([module, wrong_prefix], ALLOWED_EXTRA_PREFIXES) == [
            "rogue_mod: extra_prefixes '/api/v1/auth' не разрешён (SYS-03, раздел 6)",
            "rogue_mod: путь '/api/v1/other/x' вне ('/api/v1/rogue-mod', '/api/v1/auth')",
            "other_mod: префикс роутера '/api/v1/other_mod', ожидается '/api/v1/other-mod'",
        ]


@pytest.mark.req("SYS-06-R5")
class TestEveryRouteDeclaresAccess:
    """Каждый REST-роут модуля объявляет право через `auth_user(...)`; маркер `public=True` — Г.4."""

    def test_registry_modules(self, registry_modules: list[ModuleDefinition]) -> None:
        """Модули реестра."""
        assert checks.route_access_violations(registry_modules) == []

    def test_sample_modules(self, sample_report: dict[str, list[str]]) -> None:
        """CRUD-роуты скаффолдера объявляют права ресурса."""
        assert sample_report["route_access"] == []

    def test_routes_without_permission_are_reported(self) -> None:
        """Роут без зависимостей и роут с `auth_user()` без права обнаруживаются."""
        module = _synthetic_module(router=_router_with_routes())

        assert checks.route_access_violations([module]) == [
            "rogue_mod: ['GET'] /api/v1/rogue-mod/open не объявляет право",
            "rogue_mod: ['GET'] /api/v1/rogue-mod/authenticated-only не объявляет право",
        ]


@pytest.mark.req("SYS-06-R18")
def test_internal_routes_not_under_api_prefix() -> None:
    """Служебные пути (`/v1/health`, `/v1/ready`, `/v1/metrics`) лежат вне `/api` и `/ws` (ADR-012)."""
    # - Arrange -
    paths = {route.path or "" for route in checks.iter_routes(create_app(modules=[]).routes)}

    # - Act -
    service_paths = {path for path in paths if path.startswith("/v1/")}

    # - Assert -
    assert service_paths == {"/v1/health", "/v1/ready", "/v1/metrics"}
    assert all(path.startswith(("/api/", "/v1/")) for path in paths), sorted(paths)
