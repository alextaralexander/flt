"""Описание доменного модуля и его подключение к приложению (ADR-002, раздел 3.2).

Shared kernel не импортирует `app.modules` статически: модули загружаются по именам
из реестра `app/modules/registry.py` через `importlib`, поэтому контракт import-linter
«`app.core` не импортирует `app.modules`» соблюдается.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any

from fastapi import APIRouter
from faststream.kafka import KafkaRouter
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData


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
    """

    name: str
    metadata: MetaData
    router: APIRouter | None = None
    extra_prefixes: tuple[str, ...] = ()
    kafka_router: KafkaRouter | None = None
    ws_handlers: tuple[Any, ...] = ()
    settings: BaseSettings | None = None
    permissions: tuple[str, ...] = field(default_factory=tuple)


class ModuleLoadError(RuntimeError):
    """Модуль реестра не найден или его `module.py` не объявляет корректный `ModuleDefinition`."""


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


def load_modules(names: Iterable[str]) -> list[ModuleDefinition]:
    """Загружает описания модулей в порядке реестра (нижние уровни зависимостей — раньше)."""
    return [load_module(name) for name in names]


def module_routers(modules: Sequence[ModuleDefinition]) -> list[APIRouter]:
    """REST-роутеры модулей, у которых они есть, в порядке реестра."""
    return [module.router for module in modules if module.router is not None]


def module_kafka_routers(modules: Sequence[ModuleDefinition]) -> list[KafkaRouter]:
    """Kafka-роутеры модулей, у которых они есть, в порядке реестра."""
    return [module.kafka_router for module in modules if module.kafka_router is not None]
