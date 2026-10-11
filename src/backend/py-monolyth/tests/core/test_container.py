"""Тесты контейнера зависимостей shared kernel (ADR-004, раздел 2.6; SYS-09-R3)."""

from typing import Annotated, Protocol, runtime_checkable

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.container import Container, DependencyNotRegisteredError, container, provide


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-09-R3")]


@runtime_checkable
class Greeter(Protocol):
    """Публичный `Protocol` сервиса модуля."""

    def greet(self) -> str:
        """Приветствие."""
        ...


class EnglishGreeter:
    """Реализация модуля-владельца."""

    def greet(self) -> str:
        """Приветствие по-английски."""
        return "hello"


class FakeGreeter:
    """Подмена в тестах."""

    def greet(self) -> str:
        """Приветствие заглушки."""
        return "fake"


class TestRegistration:
    """Регистрация, разрешение и подмена реализаций."""

    def test_factory_is_called_on_each_resolve(self) -> None:
        """Фабрика вызывается при каждом разрешении: контейнер не хранит экземпляры запросов."""
        # - Arrange -
        box = Container()
        box.register(Greeter, EnglishGreeter)

        # - Act -
        first, second = box.resolve(Greeter), box.resolve(Greeter)

        # - Assert -
        assert first.greet() == "hello"
        assert first is not second

    def test_instance_registration(self) -> None:
        """Неизменяемый объект конфигурации регистрируется экземпляром."""
        # - Arrange -
        box = Container()
        greeter = EnglishGreeter()
        box.register_instance(Greeter, greeter)

        # - Act / Assert -
        assert box.resolve(Greeter) is greeter

    def test_named_registrations_are_independent(self) -> None:
        """Именованные регистрации одного типа (реестры точек расширения) не пересекаются."""
        # - Arrange -
        box = Container()
        box.register(Greeter, EnglishGreeter, name="a")
        box.register(Greeter, FakeGreeter, name="b")

        # - Act / Assert -
        assert box.resolve(Greeter, name="a").greet() == "hello"
        assert box.resolve(Greeter, name="b").greet() == "fake"
        with pytest.raises(DependencyNotRegisteredError):
            box.resolve(Greeter)

    def test_missing_registration_is_reported(self) -> None:
        """Неизвестная зависимость — понятная ошибка; `resolve_optional` возвращает None."""
        # - Arrange -
        box = Container()

        # - Act / Assert -
        with pytest.raises(DependencyNotRegisteredError, match="Greeter"):
            box.resolve(Greeter)
        assert box.resolve_optional(Greeter) is None
        assert not box.is_registered(Greeter)

    def test_double_registration_is_rejected(self) -> None:
        """Повторная регистрация без `replace=True` — ошибка (две реализации одного `Protocol`)."""
        # - Arrange -
        box = Container()
        box.register(Greeter, EnglishGreeter)

        # - Act / Assert -
        with pytest.raises(ValueError, match="уже зарегистрирован"):
            box.register(Greeter, FakeGreeter)
        box.register(Greeter, FakeGreeter, replace=True)
        assert box.resolve(Greeter).greet() == "fake"

    def test_override_is_scoped(self) -> None:
        """`override` подменяет реализацию только внутри блока, даже без регистрации."""
        # - Arrange -
        box = Container()
        box.register(Greeter, EnglishGreeter)

        # - Act / Assert -
        with box.override(Greeter, FakeGreeter()):
            assert box.resolve(Greeter).greet() == "fake"
        assert box.resolve(Greeter).greet() == "hello"
        with box.override(Greeter, FakeGreeter(), name="unregistered"):
            assert box.resolve(Greeter, name="unregistered").greet() == "fake"
        assert box.resolve_optional(Greeter, name="unregistered") is None


class TestProvide:
    """`Depends(provide(Protocol))` в контроллерах."""

    async def test_controller_gets_implementation_and_override(self) -> None:
        """Контроллер получает реализацию из процессного контейнера; тест подменяет её `override`."""
        # - Arrange -
        app = FastAPI()

        @app.get("/greet")
        async def greet(greeter: Annotated[Greeter, Depends(provide(Greeter))]) -> dict[str, str]:
            """Тестовый контроллер."""
            return {"text": greeter.greet()}

        container.register(Greeter, EnglishGreeter, replace=True)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                # - Act -
                real = await client.get("/greet")
                with container.override(Greeter, FakeGreeter()):
                    fake = await client.get("/greet")
        finally:
            # - Clean -
            container.unregister(Greeter)

        # - Assert -
        assert real.json() == {"text": "hello"}
        assert fake.json() == {"text": "fake"}
