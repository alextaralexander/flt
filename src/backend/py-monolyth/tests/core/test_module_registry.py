"""Реестр модулей: проверки прав, точек расширения и провайдера ролей при старте, установка в контейнер.

ADR-002, раздел 3.2; ADR-006, раздел 3.8; SYS-06-R2, R4; SYS-09-R1–R3.
"""

from collections.abc import Iterator, Sequence
from typing import Protocol, runtime_checkable

import pytest
from fastapi import APIRouter
from sqlalchemy import MetaData

from app.core.captcha import CaptchaProvider, StubCaptchaProvider
from app.core.container import container
from app.core.extensions import ExtensionContribution, ExtensionPoint, ExtensionRegistrationError, ExtensionRegistry
from app.core.mail import MailClient, SmtpMailClient
from app.core.modules import ModuleDefinition, ModuleLoadError, ModuleRegistry, install_modules, load_modules
from app.core.security import Grant, RolePermissionsProvider, Scope, TokenVerifier, UserFlags
from app.modules.registry import MODULES


pytestmark = pytest.mark.no_db


@runtime_checkable
class Provider(Protocol):
    """Контракт точки `alpha.providers`."""

    def kind(self) -> str:
        """Вид провайдера."""
        ...


class StubProvider:
    """Вклад `stub`."""

    def kind(self) -> str:
        """Вид `stub`."""
        return "stub"


class MatrixProvider:
    """Провайдер ролей модуля `alpha` (вместо `identity`)."""

    async def grants_for(self, roles: Sequence[str], flags: UserFlags) -> frozenset[Grant]:
        """Право чтения для любого пользователя."""
        return frozenset({Grant(code="alpha:items:read", scope=Scope.OWN)}) if roles else frozenset()

    async def denial_code(self, permission: str, roles: Sequence[str], flags: UserFlags) -> str | None:
        """Специального кода нет."""
        return None


POINT = ExtensionPoint[Provider](name="alpha.providers", version="1.0.0", contract=Provider)


def _module(name: str, **fields: object) -> ModuleDefinition:
    """Описание модуля с метаданными схемы `name`."""
    return ModuleDefinition(name=name, metadata=MetaData(schema=name), **fields)  # type: ignore[arg-type]


@pytest.fixture
def clean_container() -> Iterator[None]:
    """После теста возвращает регистрации процесса (реестр `MODULES`) и снимает реестр точки теста."""
    yield
    container.unregister(ExtensionRegistry, name="alpha.providers")
    install_modules(load_modules(MODULES))


@pytest.mark.req("SYS-09-R2")
class TestExtensionsAtLoad:
    """Точки и вклады модулей проверяются при сборке реестра."""

    def test_contribution_of_another_module(self) -> None:
        """Модуль `beta` вносит вклад в точку `alpha` — реестр точки собран."""
        # - Arrange -
        alpha = _module("alpha", extension_points=(POINT,))
        beta = _module(
            "beta",
            contributions=(
                ExtensionContribution(point="alpha.providers", point_version="^1.0", id="stub", provider=StubProvider),
            ),
        )

        # - Act -
        registry = ModuleRegistry.build([alpha, beta])

        # - Assert -
        assert list(registry) == [alpha, beta]
        assert registry.extensions["alpha.providers"].get("stub").kind() == "stub"

    @pytest.mark.req("SYS-09-R1")
    def test_point_must_belong_to_declaring_module(self) -> None:
        """Точка `alpha.*` в `ModuleDefinition` модуля `beta` — ошибка старта."""
        with pytest.raises(ModuleLoadError, match=r"alpha\.providers"):
            ModuleRegistry.build([_module("beta", extension_points=(POINT,))])

    def test_invalid_contribution_stops_start(self) -> None:
        """Вклад в необъявленную точку — ошибка старта."""
        broken = _module(
            "beta",
            contributions=(
                ExtensionContribution(point="alpha.providers", point_version="^1.0", id="stub", provider=StubProvider),
            ),
        )
        with pytest.raises(ExtensionRegistrationError, match="не объявлена"):
            ModuleRegistry.build([broken])


@pytest.mark.req("SYS-06-R2")
class TestPermissionsAtLoad:
    """Коды прав модулей проверяются при старте."""

    @pytest.mark.parametrize(
        ("permissions", "message"),
        [
            (("alpha:items:fly",), "PERMISSION_ACTIONS"),
            (("beta:items:read",), "первый сегмент"),
            (("ALPHA_READ",), "формату"),
        ],
    )
    def test_invalid_permissions(self, permissions: tuple[str, ...], message: str) -> None:
        """Неизвестное действие, чужой модуль или неверный формат — ошибка старта."""
        with pytest.raises(ModuleLoadError, match=message):
            ModuleRegistry.build([_module("alpha", permissions=permissions)])

    def test_duplicate_permission_between_modules(self) -> None:
        """Один код в двух модулях невозможен (первый сегмент), дубликат внутри модуля — ошибка."""
        with pytest.raises(ModuleLoadError, match="дважды"):
            ModuleRegistry.build([_module("alpha", permissions=("alpha:items:read", "alpha:items:read"))])

    @pytest.mark.req("SYS-03-R1")
    def test_router_prefix(self) -> None:
        """Префикс роутера — `/api/v1/<module-kebab>` (ADR-002)."""
        with pytest.raises(ModuleLoadError, match="/api/v1/alpha-mod"):
            ModuleRegistry.build([_module("alpha_mod", router=APIRouter(prefix="/api/v1/alpha_mod"))])
        assert ModuleRegistry.build([_module("alpha_mod", router=APIRouter(prefix="/api/v1/alpha-mod"))])


@pytest.mark.req("SYS-06-R4")
class TestRolePermissionsProvider:
    """Провайдер ролей регистрирует ровно один модуль (`identity`)."""

    def test_single_provider(self) -> None:
        """Провайдер модуля доступен в реестре."""
        provider = MatrixProvider()
        registry = ModuleRegistry.build([_module("alpha", role_permissions_provider=provider)])
        assert registry.role_permissions_provider is provider

    def test_two_providers_stop_start(self) -> None:
        """Два модуля с провайдером ролей — ошибка старта."""
        with pytest.raises(ModuleLoadError, match="RolePermissionsProvider"):
            ModuleRegistry.build(
                [
                    _module("alpha", role_permissions_provider=MatrixProvider()),
                    _module("beta", role_permissions_provider=MatrixProvider()),
                ]
            )

    def test_provider_must_match_protocol(self) -> None:
        """Объект без методов интерфейса — ошибка старта."""
        with pytest.raises(ModuleLoadError, match="RolePermissionsProvider"):
            ModuleRegistry.build([_module("alpha", role_permissions_provider=object())])


@pytest.mark.req("SYS-09-R3")
@pytest.mark.usefixtures("clean_container")
def test_install_registers_kernel_services() -> None:
    """`install_modules` кладёт в контейнер реестры точек, провайдер ролей и верификатор токенов."""
    # - Arrange -
    provider = MatrixProvider()
    registry = ModuleRegistry.build(
        [
            _module("alpha", extension_points=(POINT,), role_permissions_provider=provider),
            _module(
                "beta",
                contributions=(
                    ExtensionContribution(
                        point="alpha.providers", point_version="^1.0", id="stub", provider=StubProvider
                    ),
                ),
            ),
        ]
    )

    # - Act -
    install_modules(registry)

    # - Assert -
    assert container.resolve(RolePermissionsProvider) is provider
    assert container.resolve(ExtensionRegistry, name="alpha.providers").ids() == ("stub",)
    assert isinstance(container.resolve(TokenVerifier), TokenVerifier)
    assert isinstance(container.resolve(MailClient), SmtpMailClient)
    assert isinstance(container.resolve(CaptchaProvider), StubCaptchaProvider)
