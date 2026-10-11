"""Описание доменного модуля и его подключение к приложению (ADR-002, раздел 3.2).

Shared kernel не импортирует `app.modules` статически: модули загружаются по именам
из реестра `app/modules/registry.py` через `importlib`, поэтому контракт import-linter
«`app.core` не импортирует `app.modules`» соблюдается.

`load_modules` собирает `ModuleRegistry` и проверяет при старте коды прав (SYS-06-R2), префиксы
роутеров (SYS-03-R1), точки расширения и вклады (SYS-09-R1, R2) и единственность провайдера ролей
(ADR-006, раздел 3.8). `install_modules` регистрирует результат в контейнере процесса.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, overload

from fastapi import APIRouter
from faststream.kafka import KafkaRouter
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from app.core.captcha import CaptchaProvider, captcha_provider_from_settings
from app.core.container import ServiceBinding, container
from app.core.extensions.point import ExtensionContribution, ExtensionPoint
from app.core.extensions.registry import (
    ExtensionRegistry,
    build_extension_registries,
    register_extension_registries,
)
from app.core.kafka.declarations import ScheduleDeclaration, TopicDeclaration
from app.core.mail import MailClient, SmtpMailClient
from app.core.security.permissions import RolePermissionsProvider, validate_permission_code
from app.core.security.tokens import TokenVerifier


@dataclass(frozen=True)
class ModuleDefinition:
    """Всё, что shared kernel должен знать о модуле, чтобы его подключить.

    Attributes:
        name: Имя пакета модуля и схемы PostgreSQL (snake_case).
        metadata: Метаданные моделей модуля (Alembic и тесты); схема — `name`.
        router: REST-роутер модуля с префиксом `/api/v1/<name>` (ADR-004) или None.
        extra_prefixes: Дополнительные префиксы путей; единственное исключение —
            `("/api/v1/auth",)` у `identity` (OQ-12, SYS-03).
        kafka_router: Kafka-роутер модуля (подключается только в ролях `worker` и `all`) или None.
        ws_handlers: Обработчики каналов WebSocket (контракт — ADR-004, SYS-04; инфраструктура — Г.4).
        settings: Экземпляр настроек модуля с префиксом `<MODULE>_` или None.
        permissions: Коды прав модуля `<module>:<resource>:<action>` (SYS-06).
        extension_points: Точки расширения, которыми владеет модуль (SYS-09-R1).
        contributions: Вклады модуля в точки расширения (свои и чужие, SYS-09-R2).
        role_permissions_provider: Реализация `RolePermissionsProvider`; объявляет только `identity`
            (ADR-006, раздел 3.8).
        provides: Реализации `Protocol` из `public/` модуля, которые `install_modules` регистрирует
            в контейнере (ADR-004, раздел 2.6; OQ-86).
        topics: Декларации топиков модуля из `public/topics.py` (SYS-04-R21); по ним роль `migrate`
            создаёт топики и DLQ.
        schedules: Периодические задачи модуля из `schedules.py` (SYS-04-R32).
    """

    name: str
    metadata: MetaData
    router: APIRouter | None = None
    extra_prefixes: tuple[str, ...] = ()
    kafka_router: KafkaRouter | None = None
    ws_handlers: tuple[Any, ...] = ()
    settings: BaseSettings | None = None
    permissions: tuple[str, ...] = field(default_factory=tuple)
    extension_points: tuple[ExtensionPoint[Any], ...] = ()
    contributions: tuple[ExtensionContribution, ...] = ()
    role_permissions_provider: RolePermissionsProvider | None = None
    provides: tuple[ServiceBinding, ...] = ()
    topics: tuple[TopicDeclaration, ...] = ()
    schedules: tuple[ScheduleDeclaration, ...] = ()


class ModuleLoadError(RuntimeError):
    """Модуль реестра не найден, его `module.py` некорректен или описание не прошло проверки старта."""


def _check_permissions(module: ModuleDefinition) -> None:
    """Коды прав модуля: формат и действие (SYS-06-R2), первый сегмент — имя модуля, без повторов."""
    seen: set[str] = set()
    for code in module.permissions:
        try:
            validate_permission_code(code)
        except ValueError as exc:
            raise ModuleLoadError(f"Модуль {module.name}: {exc}") from exc
        if code.split(":", 1)[0] != module.name:
            raise ModuleLoadError(f"Модуль {module.name}: у кода {code!r} первый сегмент не имя модуля (SYS-06-R2).")
        if code in seen:
            raise ModuleLoadError(f"Модуль {module.name}: код {code!r} объявлен дважды (SYS-06-R2).")
        seen.add(code)


def _check_router_prefix(module: ModuleDefinition) -> None:
    """Префикс REST-роутера — `/api/v1/<module-kebab>` (SYS-03-R1, ADR-002)."""
    if module.router is None:
        return
    expected = f"/api/v1/{module.name.replace('_', '-')}"
    if module.router.prefix != expected:
        raise ModuleLoadError(
            f"Модуль {module.name}: префикс роутера {module.router.prefix!r}, ожидается {expected!r}."
        )


def _check_extension_points(module: ModuleDefinition) -> None:
    """Точки модуля называются `<module>.<point>` (SYS-09-R1)."""
    for point in module.extension_points:
        if point.module != module.name:
            raise ModuleLoadError(f"Модуль {module.name}: точка {point.name!r} должна начинаться с '{module.name}.'.")


def _check_provides(module: ModuleDefinition) -> None:
    """Фабрики вызываемы; модуль реализует только свои `Protocol` (`app.modules.<module>.public`)."""
    for binding in module.provides:
        label = getattr(binding.key, "__qualname__", repr(binding.key))
        if not callable(binding.factory):
            raise ModuleLoadError(f"Модуль {module.name}: фабрика для {label} не вызываемая.")
        owner_module = getattr(binding.key, "__module__", "")
        if owner_module.startswith("app.modules.") and not owner_module.startswith(f"app.modules.{module.name}."):
            raise ModuleLoadError(
                f"Модуль {module.name}: {label} объявлен в {owner_module}; реализацию регистрирует модуль-владелец."
            )


def _check_schedules(module: ModuleDefinition) -> None:
    """Имена периодических задач модуля уникальны (имя входит в ключ блокировки, SYS-04-R32)."""
    seen: set[str] = set()
    for schedule in module.schedules:
        if schedule.name in seen:
            raise ModuleLoadError(f"Модуль {module.name}: задача {schedule.name!r} объявлена дважды (SYS-04-R32).")
        seen.add(schedule.name)


def _check_topics(definitions: Sequence[ModuleDefinition]) -> None:
    """Модуль объявляет только свои топики; имя топика уникально в монолите (SYS-04-R19, R21)."""
    owners: dict[str, str] = {}
    for module in definitions:
        for topic in module.topics:
            if topic.module != module.name:
                raise ModuleLoadError(
                    f"Модуль {module.name}: топик {topic.name} принадлежит модулю {topic.module} (SYS-04-R19)."
                )
            if topic.name in owners:
                raise ModuleLoadError(f"Топик {topic.name} объявлен дважды (SYS-04-R19).")
            owners[topic.name] = module.name


class ModuleRegistry(Sequence[ModuleDefinition]):
    """Модули реестра в порядке зависимостей и собранные из них объекты старта.

    Attributes:
        extensions: Реестры вкладов по имени точки расширения (SYS-09-R2).
        role_permissions_provider: Провайдер ролей модуля `identity` или None.
    """

    def __init__(
        self,
        modules: Sequence[ModuleDefinition],
        extensions: Mapping[str, ExtensionRegistry[Any]],
        role_permissions_provider: RolePermissionsProvider | None,
    ) -> None:
        """Сохраняет проверенные модули и объекты старта (создаётся через `build`)."""
        self._modules = tuple(modules)
        self.extensions = dict(extensions)
        self.role_permissions_provider = role_permissions_provider

    @classmethod
    def build(cls, modules: Iterable[ModuleDefinition]) -> ModuleRegistry:
        """Проверяет описания модулей и собирает реестр (ошибка останавливает старт).

        Raises:
            ModuleLoadError: Неверные права, префикс роутера, имя точки, больше одного провайдера ролей
                или провайдер не реализует `RolePermissionsProvider`.
            ExtensionRegistrationError: Вклад не прошёл проверку SYS-09-R2.
        """
        definitions = list(modules)
        providers: list[tuple[str, RolePermissionsProvider]] = []
        for module in definitions:
            _check_permissions(module)
            _check_router_prefix(module)
            _check_extension_points(module)
            _check_provides(module)
            _check_schedules(module)
            provider = module.role_permissions_provider
            if provider is not None:
                if not isinstance(provider, RolePermissionsProvider):
                    raise ModuleLoadError(
                        f"Модуль {module.name}: провайдер ролей не реализует RolePermissionsProvider."
                    )
                providers.append((module.name, provider))
        _check_topics(definitions)
        bindings: dict[type[Any], str] = {}
        for module in definitions:
            for binding in module.provides:
                if binding.key in bindings:
                    label = getattr(binding.key, "__qualname__", repr(binding.key))
                    raise ModuleLoadError(
                        f"{label} реализуют несколько модулей: {bindings[binding.key]}, {module.name}."
                    )
                bindings[binding.key] = module.name
        if len(providers) > 1:
            names = ", ".join(name for name, _ in providers)
            raise ModuleLoadError(f"RolePermissionsProvider объявлен несколькими модулями: {names} (только identity).")

        extensions = build_extension_registries(
            [point for module in definitions for point in module.extension_points],
            [contribution for module in definitions for contribution in module.contributions],
        )
        return cls(definitions, extensions, providers[0][1] if providers else None)

    @overload
    def __getitem__(self, index: int) -> ModuleDefinition: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[ModuleDefinition]: ...

    def __getitem__(self, index: int | slice) -> ModuleDefinition | Sequence[ModuleDefinition]:
        """Модуль (или срез модулей) по позиции в реестре."""
        return self._modules[index]

    def __len__(self) -> int:
        """Число модулей."""
        return len(self._modules)

    def __iter__(self) -> Iterator[ModuleDefinition]:
        """Модули в порядке реестра."""
        return iter(self._modules)


def load_module(name: str) -> ModuleDefinition:
    """Импортирует `app.modules.<name>.module` и возвращает объявленный там `module`.

    Args:
        name: Имя модуля из реестра.

    Returns:
        Описание модуля.

    Raises:
        ModuleLoadError: пакета модуля нет, в `module.py` нет `ModuleDefinition`
            или его имя не совпадает с именем пакета.
    """
    try:
        definition_module = import_module(f"app.modules.{name}.module")
    except ModuleNotFoundError as exc:
        raise ModuleLoadError(f"Модуль `{name}` из реестра не найден: нет пакета app/modules/{name}.") from exc

    definition = getattr(definition_module, "module", None)
    if not isinstance(definition, ModuleDefinition):
        raise ModuleLoadError(f"В app/modules/{name}/module.py нет объекта `module: ModuleDefinition`.")
    if definition.name != name:
        raise ModuleLoadError(f"Имя в ModuleDefinition ({definition.name!r}) не совпадает с пакетом `{name}`.")
    return definition


def load_modules(names: Iterable[str]) -> ModuleRegistry:
    """Загружает и проверяет модули в порядке реестра (нижние уровни зависимостей — раньше)."""
    return ModuleRegistry.build(load_module(name) for name in names)


def install_modules(registry: ModuleRegistry) -> None:
    """Регистрирует объекты старта в контейнере процесса (ADR-004, раздел 2.6).

    - реестры точек расширения — под именами точек (SYS-09-R3);
    - провайдер ролей `identity` (без него — запрет всего, SYS-06-R4);
    - `TokenVerifier` из настроек процесса (ключи неизменны в процессе, ADR-006);
    - `MailClient` (SMTP, OQ-11) и `CaptchaProvider` (по `CAPTCHA_PROVIDER`, OQ-10) — фабрики из настроек;
    - реализации `Protocol` модулей из `ModuleDefinition.provides` (OQ-86).

    Повторный вызов (пересборка приложения в тестах) заменяет регистрации.
    """
    register_extension_registries(registry.extensions)
    for module in registry:
        for binding in module.provides:
            container.register(binding.key, binding.factory, replace=True)
    if registry.role_permissions_provider is None:
        container.unregister(RolePermissionsProvider)
    else:
        container.register_instance(RolePermissionsProvider, registry.role_permissions_provider, replace=True)
    container.register_instance(TokenVerifier, TokenVerifier.from_settings(), replace=True)
    container.register(MailClient, SmtpMailClient.from_settings, replace=True)
    container.register_instance(CaptchaProvider, captcha_provider_from_settings(), replace=True)


def module_routers(modules: Sequence[ModuleDefinition]) -> list[APIRouter]:
    """REST-роутеры модулей, у которых они есть, в порядке реестра."""
    return [module.router for module in modules if module.router is not None]


def module_kafka_routers(modules: Sequence[ModuleDefinition]) -> list[KafkaRouter]:
    """Kafka-роутеры модулей, у которых они есть, в порядке реестра."""
    return [module.kafka_router for module in modules if module.kafka_router is not None]
