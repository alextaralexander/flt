"""Реестр вкладов точки расширения и его сборка при старте (SYS-09-R2, R3).

`build_extension_registries` проверяет вклады всех модулей реестра: точка объявлена, версия
совместима, `id` уникален и по формату, экземпляр фабрики соответствует контракту, у точки
`single` ровно один вклад. Нарушение — `ExtensionRegistrationError`, процесс не стартует.
Реестры неизменяемы и одинаковы на всех инстансах (SYS-05: в памяти — только неизменяемая
конфигурация); модули получают их через контейнер (`provide_registry`).
"""

import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from app.core.container import container
from app.core.extensions.point import (
    CONTRIBUTION_ID_RE,
    SEMVER_RE,
    ExtensionContribution,
    ExtensionPoint,
    is_protocol,
)


CARET_RE = re.compile(r"^\^(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?(?:\.(0|[1-9]\d*))?$")


class ExtensionRegistrationError(RuntimeError):
    """Вклад или точка не прошли проверку при старте процесса (SYS-09-R2)."""


@dataclass(frozen=True)
class RegisteredContribution[T]:
    """Проверенный вклад: экземпляр фабрики и исходная декларация."""

    id: str
    instance: T
    contribution: ExtensionContribution


class ExtensionRegistry[T]:
    """Неизменяемый реестр вкладов одной точки, упорядоченный по `order`, затем по `id`."""

    def __init__(self, point: ExtensionPoint[T], items: Sequence[RegisteredContribution[T]]) -> None:
        """Сохраняет точку и упорядоченные проверенные вклады."""
        self.point = point
        self._items = tuple(sorted(items, key=lambda item: (item.contribution.order, item.id)))
        self._by_id = {item.id: item for item in self._items}

    def ids(self) -> tuple[str, ...]:
        """Идентификаторы вкладов в порядке реестра."""
        return tuple(item.id for item in self._items)

    def get(self, contribution_id: str) -> T:
        """Экземпляр вклада по `id`.

        Raises:
            KeyError: Вклада с таким `id` нет (вызывающий решает, какую ошибку вернуть клиенту).
        """
        item = self._by_id.get(contribution_id)
        if item is None:
            raise KeyError(f"В точке {self.point.name!r} нет вклада {contribution_id!r}.")
        return item.instance

    def one(self) -> T:
        """Единственный вклад точки `single`."""
        if len(self._items) != 1:
            raise LookupError(f"В точке {self.point.name!r} не ровно один вклад.")
        return self._items[0].instance

    def __iter__(self) -> Iterator[T]:
        """Экземпляры вкладов в порядке реестра."""
        return (item.instance for item in self._items)

    def __len__(self) -> int:
        """Число вкладов."""
        return len(self._items)

    def __contains__(self, contribution_id: object) -> bool:
        """Есть ли вклад с таким `id`."""
        return contribution_id in self._by_id


def _version_compatible(requirement: str, version: str) -> bool:
    """Совместимость по caret: та же мажорная версия и не ниже требуемой (`^1.2` ↔ 1.2.0…1.x.y)."""
    match = CARET_RE.match(requirement)
    point_match = SEMVER_RE.match(version)
    if match is None or point_match is None:
        raise ExtensionRegistrationError(f"Требование версии {requirement!r} не по формату ^MAJOR[.MINOR[.PATCH]].")
    required = tuple(int(part or 0) for part in match.groups())
    actual = tuple(int(part) for part in point_match.groups())
    return actual[0] == required[0] and actual >= required


def _instantiate[T](point: ExtensionPoint[T], contribution: ExtensionContribution) -> T:
    """Экземпляр фабрики вклада, проверенный по контракту точки."""
    where = f"Вклад {contribution.id!r} в точку {point.name!r}"
    instance = contribution.provider()
    if point.is_model_contract:
        model = cast("type[BaseModel]", point.contract)
        if isinstance(instance, model):
            return cast("T", instance)
        try:
            return cast("T", model.model_validate(instance))
        except ValidationError as exc:
            raise ExtensionRegistrationError(f"{where} не проходит контракт {model.__name__}: {exc}") from exc
    if not isinstance(instance, point.contract):
        kind = "Protocol" if is_protocol(point.contract) else "класс"
        raise ExtensionRegistrationError(f"{where} не соответствует контракту ({kind} {point.contract.__name__}).")
    return instance


def build_extension_registries(
    points: Iterable[ExtensionPoint[Any]], contributions: Iterable[ExtensionContribution]
) -> dict[str, ExtensionRegistry[Any]]:
    """Проверяет вклады и собирает реестр каждой точки (SYS-09-R2).

    Args:
        points: Все точки модулей реестра.
        contributions: Все вклады модулей реестра.

    Returns:
        Реестры по имени точки.

    Raises:
        ExtensionRegistrationError: Точка объявлена дважды; вклад в необъявленную точку, с
            несовместимой версией, дубликатом или неверным `id`, не по контракту; у точки
            `single` не ровно один вклад.
    """
    declared: dict[str, ExtensionPoint[Any]] = {}
    for point in points:
        if point.name in declared:
            raise ExtensionRegistrationError(f"Точка расширения {point.name!r} объявлена дважды.")
        declared[point.name] = point

    collected: dict[str, list[RegisteredContribution[Any]]] = {name: [] for name in declared}
    for contribution in contributions:
        target = declared.get(contribution.point)
        if target is None:
            raise ExtensionRegistrationError(f"Вклад {contribution.id!r}: точка {contribution.point!r} не объявлена.")
        if not CONTRIBUTION_ID_RE.match(contribution.id):
            raise ExtensionRegistrationError(
                f"Вклад в {target.name!r}: id {contribution.id!r} не по формату [a-z][a-z0-9_]*."
            )
        if not _version_compatible(contribution.point_version, target.version):
            raise ExtensionRegistrationError(
                f"Вклад {contribution.id!r} требует {contribution.point_version}, "
                f"несовместим с точкой {target.name!r} {target.version}."
            )
        if any(item.id == contribution.id for item in collected[target.name]):
            raise ExtensionRegistrationError(f"Вклад {contribution.id!r} в точку {target.name!r} — дубликат id.")
        collected[target.name].append(
            RegisteredContribution(contribution.id, _instantiate(target, contribution), contribution)
        )

    for name, items in collected.items():
        if declared[name].cardinality == "single" and len(items) != 1:
            raise ExtensionRegistrationError(
                f"Точка {name!r} (single) требует ровно один вклад, получено {len(items)}."
            )
    return {name: ExtensionRegistry(declared[name], items) for name, items in collected.items()}


def register_extension_registries(registries: Mapping[str, ExtensionRegistry[Any]]) -> None:
    """Регистрирует реестры в контейнере процесса под именами точек (SYS-09-R3)."""
    for name, registry in registries.items():
        container.register_instance(ExtensionRegistry, registry, name=name, replace=True)


def provide_registry(point_name: str) -> Callable[[], ExtensionRegistry[Any]]:
    """Зависимость FastAPI: `Depends(provide_registry("llm_gateway.providers"))` (SYS-09-R3)."""

    def dependency() -> ExtensionRegistry[Any]:
        return container.resolve(ExtensionRegistry, name=point_name)

    dependency.__doc__ = f"Реестр вкладов точки {point_name} из контейнера shared kernel."
    return dependency
