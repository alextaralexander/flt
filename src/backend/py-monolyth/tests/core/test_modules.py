"""Тесты описания и загрузки модулей (`app.core.modules`, ADR-002 раздел 3.2)."""

import sys
import types
from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from faststream.kafka import KafkaRouter
from sqlalchemy import MetaData

from app.core.modules import (
    ModuleDefinition,
    ModuleLoadError,
    load_module,
    load_modules,
    module_kafka_routers,
    module_routers,
)
from app.modules.registry import MODULES


pytestmark = pytest.mark.no_db


@pytest.fixture
def fake_module_package() -> Iterator[types.ModuleType]:
    """Регистрирует в `sys.modules` пакет `app.modules.fake_mod.module` (без файлов на диске)."""
    module_py = types.ModuleType("app.modules.fake_mod.module")
    sys.modules["app.modules.fake_mod"] = types.ModuleType("app.modules.fake_mod")
    sys.modules["app.modules.fake_mod.module"] = module_py
    yield module_py
    sys.modules.pop("app.modules.fake_mod.module", None)
    sys.modules.pop("app.modules.fake_mod", None)


class TestLoadModule:
    """Загрузка `ModuleDefinition` по имени модуля (Arrange / Act / Assert)."""

    def test_returns_declared_definition(self, fake_module_package: types.ModuleType) -> None:
        """Возвращается объект `module` из `app.modules.<name>.module`."""
        # - Arrange -
        definition = ModuleDefinition(name="fake_mod", metadata=MetaData(schema="fake_mod"))
        fake_module_package.module = definition  # type: ignore[attr-defined]

        # - Act -
        loaded = load_modules(["fake_mod"])

        # - Assert -
        assert loaded == [definition]

    def test_missing_package_is_reported(self) -> None:
        """Модуль из реестра без пакета — понятная ошибка."""
        # - Act / Assert -
        with pytest.raises(ModuleLoadError, match="не найден"):
            load_module("module_that_does_not_exist")

    def test_missing_definition_is_reported(self, fake_module_package: types.ModuleType) -> None:
        """`module.py` без объекта `module: ModuleDefinition` — ошибка."""
        # - Arrange -
        fake_module_package.module = object()  # type: ignore[attr-defined]

        # - Act / Assert -
        with pytest.raises(ModuleLoadError, match="ModuleDefinition"):
            load_module("fake_mod")

    def test_name_mismatch_is_reported(self, fake_module_package: types.ModuleType) -> None:
        """Имя в описании должно совпадать с именем пакета (оно же схема PostgreSQL)."""
        # - Arrange -
        fake_module_package.module = ModuleDefinition(  # type: ignore[attr-defined]
            name="other_name", metadata=MetaData(schema="other_name")
        )

        # - Act / Assert -
        with pytest.raises(ModuleLoadError, match="не совпадает"):
            load_module("fake_mod")


class TestModuleRouters:
    """Выборка роутеров модулей для сборки приложений."""

    def test_only_present_routers_in_registry_order(self) -> None:
        """Модули без роутера пропускаются, порядок реестра сохраняется."""
        # - Arrange -
        rest_router = APIRouter(prefix="/api/v1/first")
        kafka_router = KafkaRouter()
        modules = [
            ModuleDefinition(name="first", metadata=MetaData(schema="first"), router=rest_router),
            ModuleDefinition(name="second", metadata=MetaData(schema="second"), kafka_router=kafka_router),
        ]

        # - Act / Assert -
        assert module_routers(modules) == [rest_router]
        assert module_kafka_routers(modules) == [kafka_router]


def test_registry_modules_are_loadable() -> None:
    """Каждый модуль реестра загружается (реестр на этапе 1 Г.1 может быть пустым)."""
    # - Act -
    loaded = load_modules(MODULES)

    # - Assert -
    assert [module.name for module in loaded] == list(MODULES)
