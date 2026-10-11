"""Минимальный контейнер зависимостей shared kernel (ADR-004, раздел 2.6).

Публичный API модуля экспортирует `typing.Protocol` сервисов; реализацию модуль-владелец
регистрирует при подключении, а вызывающие получают её через контейнер:

- в контроллерах — `Depends(provide(IdentityService))`;
- в консьюмерах Kafka и планировщике — `container.resolve(IdentityService)`;
- в тестах — `with container.override(IdentityService, fake): ...`.

Контейнер хранит только фабрики и неизменяемые объекты конфигурации, зарегистрированные при
старте процесса (одинаковые на всех инстансах); экземпляры сервисов создаются фабрикой при
каждом разрешении и между запросами не живут (SYS-05-R1). Именованные регистрации нужны для
нескольких объектов одного типа — например реестров точек расширения (SYS-09-R3).
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, cast


type _Key = tuple[type[Any], str | None]


@dataclass(frozen=True)
class ServiceBinding:
    """Реализация `Protocol` из `public/` модуля для контейнера (`ModuleDefinition.provides`, OQ-86).

    Attributes:
        key: Тип `Protocol`, который модуль экспортирует в `public/`.
        factory: Фабрика без аргументов; вызывается при каждом `resolve` (экземпляры между
            запросами не живут, SYS-05-R1).
    """

    key: type[Any]
    factory: Callable[[], Any]


class DependencyNotRegisteredError(LookupError):
    """Для запрошенного типа (и имени) нет ни регистрации, ни подмены."""


def _describe(key: type[Any], name: str | None) -> str:
    """Человекочитаемое имя регистрации для сообщений об ошибках."""
    label = getattr(key, "__qualname__", repr(key))
    return f"{label}[{name}]" if name else label


class Container:
    """Реестр фабрик по типу `Protocol` (и необязательному имени) с подменой для тестов."""

    def __init__(self) -> None:
        """Создаёт пустой контейнер."""
        self._factories: dict[_Key, Callable[[], Any]] = {}
        self._overrides: dict[_Key, Any] = {}

    def register[T](
        self, key: type[T], factory: Callable[[], T], *, name: str | None = None, replace: bool = False
    ) -> None:
        """Регистрирует фабрику реализации `key`.

        Args:
            key: Тип (обычно `Protocol` из `public/` модуля).
            factory: Фабрика без аргументов; вызывается при каждом `resolve`.
            name: Имя регистрации для нескольких объектов одного типа.
            replace: Разрешить замену существующей регистрации (повторная сборка приложения).

        Raises:
            ValueError: Регистрация уже есть, а `replace` не задан.
        """
        slot = (key, name)
        if slot in self._factories and not replace:
            raise ValueError(f"{_describe(key, name)} уже зарегистрирован в контейнере.")
        self._factories[slot] = factory

    def register_instance[T](
        self, key: type[T], instance: T, *, name: str | None = None, replace: bool = False
    ) -> None:
        """Регистрирует готовый неизменяемый объект (настройки, реестр, провайдер ролей)."""
        self.register(key, lambda: instance, name=name, replace=replace)

    def unregister(self, key: type[Any], *, name: str | None = None) -> None:
        """Удаляет регистрацию, если она есть (тесты и пересборка приложения)."""
        self._factories.pop((key, name), None)

    def is_registered(self, key: type[Any], *, name: str | None = None) -> bool:
        """Есть ли регистрация или подмена для `key`."""
        return (key, name) in self._overrides or (key, name) in self._factories

    def resolve[T](self, key: type[T], *, name: str | None = None) -> T:
        """Реализация `key`: подмена теста или результат зарегистрированной фабрики.

        Raises:
            DependencyNotRegisteredError: Нет ни подмены, ни регистрации.
        """
        slot = (key, name)
        if slot in self._overrides:
            return cast("T", self._overrides[slot])
        factory = self._factories.get(slot)
        if factory is None:
            raise DependencyNotRegisteredError(f"{_describe(key, name)} не зарегистрирован в контейнере.")
        return cast("T", factory())

    def resolve_optional[T](self, key: type[T], *, name: str | None = None) -> T | None:
        """Реализация `key` или None, если она не зарегистрирована."""
        return self.resolve(key, name=name) if self.is_registered(key, name=name) else None

    @contextmanager
    def override[T](self, key: type[T], implementation: T, *, name: str | None = None) -> Iterator[T]:
        """Подменяет реализацию `key` на время блока (тесты); вложенные подмены восстанавливаются."""
        slot = (key, name)
        missing = object()
        previous = self._overrides.get(slot, missing)
        self._overrides[slot] = implementation
        try:
            yield implementation
        finally:
            if previous is missing:
                self._overrides.pop(slot, None)
            else:
                self._overrides[slot] = previous


container = Container()
"""Контейнер процесса: заполняется при старте по реестру модулей (`app.core.modules.install_modules`)."""


def provide[T](key: type[T], *, name: str | None = None) -> Callable[[], T]:
    """Зависимость FastAPI: `Depends(provide(IdentityService))` разрешает реализацию на каждый запрос."""

    def dependency() -> T:
        return container.resolve(key, name=name)

    dependency.__doc__ = f"Реализация {_describe(key, name)} из контейнера shared kernel."
    return dependency
