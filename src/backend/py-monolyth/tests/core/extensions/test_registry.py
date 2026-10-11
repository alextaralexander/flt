"""Тесты точек расширения и реестра вкладов (SYS-09-R1, R2, R3)."""

from dataclasses import dataclass
from typing import Annotated, Protocol, runtime_checkable

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.core.container import container
from app.core.extensions import (
    ExtensionContribution,
    ExtensionPoint,
    ExtensionRegistrationError,
    ExtensionRegistry,
    build_extension_registries,
    provide_registry,
)


pytestmark = pytest.mark.no_db


@runtime_checkable
class Provider(Protocol):
    """Контракт точки `owner.providers`."""

    def kind(self) -> str:
        """Вид провайдера."""
        ...


class StubProvider:
    """Вклад `stub`."""

    def kind(self) -> str:
        """Вид `stub`."""
        return "stub"


class OpenAIProvider:
    """Вклад `openai_compatible`."""

    def kind(self) -> str:
        """Вид `openai_compatible`."""
        return "openai_compatible"


class NotAProvider:
    """Объект без метода контракта."""


class ExamDefinition(BaseModel):
    """Декларативный вклад-модель (экзамен)."""

    code: str


@dataclass(frozen=True)
class KindInfo:
    """Вклад-датакласс (как `ProviderKindInfo` из примера SYS-09)."""

    kind: str


PROVIDERS = ExtensionPoint[Provider](name="owner.providers", version="1.2.0", contract=Provider)
EXAMS = ExtensionPoint[ExamDefinition](name="owner.exams", version="1.0.0", contract=ExamDefinition)
SINGLE = ExtensionPoint[Provider](name="owner.default", version="1.0.0", contract=Provider, cardinality="single")


def _contribution(point: str = "owner.providers", id: str = "stub", **kwargs: object) -> ExtensionContribution:
    """Вклад с параметрами по умолчанию."""
    fields: dict[str, object] = {"point": point, "point_version": "^1.0", "id": id, "provider": StubProvider}
    fields.update(kwargs)
    return ExtensionContribution(**fields)  # type: ignore[arg-type]


@pytest.mark.req("SYS-09-R1")
class TestExtensionPointDeclaration:
    """Объявление точки: имя `<module>.<point>`, semver, контракт, кратность."""

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"name": "providers"}, "<module>.<point>"),
            ({"name": "Owner.Providers"}, "<module>.<point>"),
            ({"version": "1.0"}, "semver"),
            ({"cardinality": "few"}, "cardinality"),
        ],
    )
    def test_invalid_declaration(self, kwargs: dict[str, object], message: str) -> None:
        """Неверное имя, версия не semver, неизвестная кратность — `ValueError` при объявлении."""
        fields: dict[str, object] = {"name": "owner.providers", "version": "1.0.0", "contract": Provider, **kwargs}
        with pytest.raises(ValueError, match=message):
            ExtensionPoint(**fields)  # type: ignore[arg-type]

    def test_protocol_contract_must_be_runtime_checkable(self) -> None:
        """`Protocol` без `@runtime_checkable` нельзя проверить `isinstance` — ошибка объявления."""

        class Plain(Protocol):
            """Контракт без runtime_checkable."""

            def kind(self) -> str:
                """Вид."""
                ...

        with pytest.raises(ValueError, match="runtime_checkable"):
            ExtensionPoint(name="owner.plain", version="1.0.0", contract=Plain)

    def test_owner_module(self) -> None:
        """Модуль-владелец — первый сегмент имени."""
        assert PROVIDERS.module == "owner"


@pytest.mark.req("SYS-09-R2")
class TestRegistration:
    """Проверки вкладов при старте (`load_modules`): нарушение останавливает процесс."""

    def test_contributions_are_ordered_and_resolved(self) -> None:
        """Вклады упорядочены по `order`, затем `id`; `get` отдаёт проверенный экземпляр."""
        # - Arrange -
        contributions = [
            _contribution(id="openai_compatible", provider=OpenAIProvider, order=200),
            _contribution(id="stub", order=100),
        ]

        # - Act -
        registries = build_extension_registries([PROVIDERS], contributions)

        # - Assert -
        registry = registries["owner.providers"]
        assert registry.ids() == ("stub", "openai_compatible")
        assert registry.get("openai_compatible").kind() == "openai_compatible"
        assert [item.kind() for item in registry] == ["stub", "openai_compatible"]
        assert "stub" in registry
        assert len(registry) == 2

    def test_model_and_dataclass_contracts(self) -> None:
        """Контракт-модель Pydantic валидирует вклад (dict → модель); датакласс — `isinstance`."""
        # - Arrange -
        kinds = ExtensionPoint[KindInfo](name="owner.kinds", version="1.0.0", contract=KindInfo)
        contributions = [
            _contribution("owner.exams", "toefl", provider=lambda: {"code": "toefl"}),
            _contribution("owner.kinds", "local", provider=lambda: KindInfo(kind="local")),
        ]

        # - Act -
        registries = build_extension_registries([EXAMS, kinds], contributions)

        # - Assert -
        assert registries["owner.exams"].get("toefl") == ExamDefinition(code="toefl")
        assert registries["owner.kinds"].get("local").kind == "local"

    def test_point_without_contributions_is_empty(self) -> None:
        """Точка `many` без вкладов — пустой реестр; неизвестный id — `KeyError`."""
        registry = build_extension_registries([PROVIDERS], [])["owner.providers"]
        assert registry.ids() == ()
        with pytest.raises(KeyError, match="nope"):
            registry.get("nope")

    @pytest.mark.parametrize(
        ("contributions", "message"),
        [
            pytest.param([_contribution("owner.unknown")], "не объявлена", id="unknown-point"),
            pytest.param([_contribution(point_version="^2.0")], "несовместим", id="major-mismatch"),
            pytest.param([_contribution(point_version="^1.3")], "несовместим", id="minor-too-new"),
            pytest.param([_contribution(point_version="1.0")], "\\^MAJOR", id="not-caret"),
            pytest.param([_contribution(), _contribution()], "дубликат", id="duplicate-id"),
            pytest.param([_contribution(id="Bad-Id")], "id", id="bad-id"),
            pytest.param([_contribution(provider=NotAProvider)], "контракт", id="contract-mismatch"),
            pytest.param([_contribution("owner.exams", "x", provider=lambda: {"nope": 1})], "контракт", id="model"),
        ],
    )
    def test_invalid_contribution_stops_start(self, contributions: list[ExtensionContribution], message: str) -> None:
        """Неизвестная точка, несовместимая версия, дубликат, неверный id, нарушение контракта — ошибка."""
        with pytest.raises(ExtensionRegistrationError, match=message):
            build_extension_registries([PROVIDERS, EXAMS], contributions)

    def test_compatible_versions(self) -> None:
        """`^1.0`, `^1.2` и `^1.2.0` совместимы с точкой 1.2.0."""
        contributions = [
            _contribution(id="a", point_version="^1.0"),
            _contribution(id="b", point_version="^1.2"),
            _contribution(id="c", point_version="^1.2.0"),
        ]
        assert build_extension_registries([PROVIDERS], contributions)["owner.providers"].ids() == ("a", "b", "c")

    @pytest.mark.parametrize("count", [0, 2])
    def test_single_requires_exactly_one(self, count: int) -> None:
        """Точка `single` требует ровно один вклад."""
        contributions = [_contribution("owner.default", f"c{index}") for index in range(count)]
        with pytest.raises(ExtensionRegistrationError, match="ровно один"):
            build_extension_registries([SINGLE], contributions)

    def test_single_one(self) -> None:
        """`single` с одним вкладом — `one()` возвращает его."""
        registry = build_extension_registries([SINGLE], [_contribution("owner.default", "only")])["owner.default"]
        assert registry.one().kind() == "stub"

    def test_duplicate_point_name(self) -> None:
        """Две точки с одним именем — ошибка."""
        with pytest.raises(ExtensionRegistrationError, match="дважды"):
            build_extension_registries([PROVIDERS, PROVIDERS], [])


@pytest.mark.req("SYS-09-R3")
class TestRegistryViaContainer:
    """Модули получают вклады через контейнер, без импорта реализаций."""

    async def test_resolve_and_override(self) -> None:
        """`container.resolve(ExtensionRegistry, name=...)`, `Depends(provide_registry(...))` и подмена в тестах."""
        # - Arrange -
        registry = build_extension_registries([PROVIDERS], [_contribution()])["owner.providers"]
        fake = build_extension_registries([PROVIDERS], [_contribution(id="fake", provider=OpenAIProvider)])[
            "owner.providers"
        ]
        app = FastAPI()

        @app.get("/kinds")
        async def kinds(
            providers: Annotated[ExtensionRegistry[Provider], Depends(provide_registry("owner.providers"))],
        ) -> list[str]:
            """Тестовый контроллер."""
            return list(providers.ids())

        container.register_instance(ExtensionRegistry, registry, name="owner.providers", replace=True)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                # - Act -
                real = (await client.get("/kinds")).json()
                with container.override(ExtensionRegistry, fake, name="owner.providers"):
                    overridden = (await client.get("/kinds")).json()
        finally:
            # - Clean -
            container.unregister(ExtensionRegistry, name="owner.providers")

        # - Assert -
        assert container.resolve_optional(ExtensionRegistry, name="owner.providers") is None
        assert real == ["stub"]
        assert overridden == ["fake"]
