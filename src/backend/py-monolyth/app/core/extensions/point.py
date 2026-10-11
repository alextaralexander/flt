"""Объявление точки расширения и вклада в неё (SYS-09-R1, R2).

Точку объявляет модуль-владелец в `public/extension_points.py` и перечисляет в
`ModuleDefinition.extension_points`; вклад — модуль, вносящий реализацию, в
`ModuleDefinition.contributions`. Проверку вкладов выполняет `load_modules` при старте процесса.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel


POINT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CONTRIBUTION_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
CARDINALITIES = ("many", "single")


def is_protocol(contract: type[Any]) -> bool:
    """Контракт — класс `typing.Protocol`."""
    return bool(getattr(contract, "_is_protocol", False))


@dataclass(frozen=True)
class ExtensionPoint[T]:
    """Точка расширения: имя `<module>.<point>`, semver контракта, контракт и кратность (SYS-09-R1).

    Attributes:
        name: Имя `<module>.<point>`; первый сегмент — модуль-владелец.
        version: Версия контракта `MAJOR.MINOR.PATCH` (SYS-09-R4).
        contract: `Protocol` с `@runtime_checkable`, модель Pydantic (декларативные вклады) или класс,
            экземпляром которого должен быть вклад.
        cardinality: `many` — несколько вкладов, `single` — ровно один.
        stage: Этап разработки, с которого точка действует.
    """

    name: str
    version: str
    contract: type[T]
    cardinality: Literal["many", "single"] = "many"
    stage: int = 1

    def __post_init__(self) -> None:
        """Проверяет объявление точки (ошибка — при импорте `public/extension_points.py`).

        Raises:
            ValueError: Имя, версия или кратность не по формату, `Protocol` без `@runtime_checkable`.
        """
        if not POINT_NAME_RE.match(self.name):
            raise ValueError(f"Имя точки расширения {self.name!r} не по формату <module>.<point> (SYS-09-R1).")
        if not SEMVER_RE.match(self.version):
            raise ValueError(f"Версия точки {self.name!r} {self.version!r} не semver MAJOR.MINOR.PATCH (SYS-09-R1).")
        if self.cardinality not in CARDINALITIES:
            raise ValueError(f"cardinality точки {self.name!r} — одно из {CARDINALITIES}, а не {self.cardinality!r}.")
        if is_protocol(self.contract) and not getattr(self.contract, "_is_runtime_protocol", False):
            raise ValueError(f"Контракт точки {self.name!r} — Protocol без @runtime_checkable (SYS-09-R1).")

    @property
    def module(self) -> str:
        """Модуль-владелец точки."""
        return self.name.split(".", 1)[0]

    @property
    def is_model_contract(self) -> bool:
        """Контракт — модель Pydantic (декларативный вклад)."""
        return isinstance(self.contract, type) and issubclass(self.contract, BaseModel)


@dataclass(frozen=True)
class ExtensionContribution:
    """Вклад модуля в точку расширения; регистрируется в `ModuleDefinition.contributions` (SYS-09-R2).

    Attributes:
        point: Имя точки `<module>.<point>`.
        point_version: Требование совместимости `^MAJOR[.MINOR[.PATCH]]`, например `^1.0`.
        id: Идентификатор вклада, уникальный в точке (`[a-z][a-z0-9_]*`).
        provider: Фабрика экземпляра без аргументов; вызывается при старте.
        order: Порядок вклада в реестре (по возрастанию, затем по `id`).
    """

    point: str
    point_version: str
    id: str
    provider: Callable[[], object]
    order: int = 100
