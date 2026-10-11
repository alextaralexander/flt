"""Модуль владеет своей схемой PostgreSQL (ADR-002 §3.4, §3.6; ADR-003; SYS-01-R8, R9; SYS-05-R7).

Проверки идут по `ModuleDefinition.metadata` модулей реестра, по модулям-образцам скаффолдера
(отчёт копии дерева) и по синтетическому модулю-нарушителю, который доказывает, что проверка
не пустая. Проверки по `information_schema` после `make migrate` требуют БД и в job `architecture`
(без PostgreSQL) не выполняются: таблицы создаются только миграциями из тех же метаданных.
"""

from uuid import UUID

import pytest
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.dao.db_helpers.base import make_module_base
from app.core.modules import ModuleDefinition
from tests.architecture import checks


pytestmark = pytest.mark.no_db


def _synthetic_module() -> ModuleDefinition:
    """Модуль `rogue` с нарушениями: FK в чужую схему, таблица вне схемы модуля, нет обязательных колонок."""
    base: type[DeclarativeBase] = make_module_base("rogue")

    class Good(base):
        """Таблица по SYS-05-R7."""

        __tablename__ = "good"
        id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
        created_at = mapped_column(DateTime(timezone=True))
        updated_at = mapped_column(DateTime(timezone=True))
        version: Mapped[int] = mapped_column(Integer)
        owner_id = mapped_column(ForeignKey("rogue.good.id"))
        foreign_user_id = mapped_column(ForeignKey("identity.user.id"))

    class Bad(base):
        """Таблица без `version` и с `created_at` без часового пояса."""

        __tablename__ = "bad"
        id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
        created_at = mapped_column(DateTime(timezone=False))
        updated_at = mapped_column(DateTime(timezone=True))

    class Technical(base):
        """Техническая таблица модели с `__flt_technical__ = True`."""

        __tablename__ = "delivery_log"
        __flt_technical__ = True
        id: Mapped[int] = mapped_column(Integer, primary_key=True)

    Table("outbox", base.metadata, Column("id", Integer, primary_key=True))
    Table("leaked", base.metadata, Column("id", String, primary_key=True), schema="public")
    # Подклассы `DeclarativeBase` хранятся слабыми ссылками: удерживаем модели, пока жив модуль.
    base.metadata.info["models"] = (Good, Bad, Technical)
    return ModuleDefinition(name="rogue", metadata=base.metadata)


@pytest.fixture(scope="module")
def synthetic_module() -> ModuleDefinition:
    """Синтетический модуль-нарушитель (создаётся один раз: декларативные классы регистрируются глобально)."""
    return _synthetic_module()


@pytest.mark.req("SYS-01-R9")
class TestNoCrossModuleForeignKeys:
    """Ни одна таблица модуля не ссылается `ForeignKey` на таблицу другой схемы."""

    def test_registry_modules(self, registry_modules: list[ModuleDefinition]) -> None:
        """Модули реестра."""
        assert checks.cross_schema_fk_violations(registry_modules) == []

    def test_sample_modules(self, sample_report: dict[str, list[str]]) -> None:
        """Модули-образцы скаффолдера."""
        assert sample_report["cross_schema_fk"] == []

    def test_foreign_schema_reference_is_reported(self, synthetic_module: ModuleDefinition) -> None:
        """FK в `identity.user` обнаруживается, FK внутри своей схемы — нет."""
        assert checks.cross_schema_fk_violations([synthetic_module]) == [
            "rogue: rogue.good.foreign_user_id → identity.user.id"
        ]


@pytest.mark.req("SYS-01-R8")
class TestModuleTablesLiveInModuleSchema:
    """Все таблицы `module.metadata` имеют `schema == module.name`."""

    def test_registry_modules(self, registry_modules: list[ModuleDefinition]) -> None:
        """Модули реестра."""
        assert checks.table_schema_violations(registry_modules) == []

    def test_sample_modules(self, sample_report: dict[str, list[str]]) -> None:
        """Модули-образцы скаффолдера."""
        assert sample_report["table_schema"] == []

    def test_table_outside_module_schema_is_reported(self, synthetic_module: ModuleDefinition) -> None:
        """Таблица со схемой `public` в метаданных модуля обнаруживается."""
        assert checks.table_schema_violations([synthetic_module]) == ["rogue: таблица public.leaked в схеме 'public'"]


@pytest.mark.req("SYS-05-R7")
class TestPublicSchemaHasNoTables:
    """Схема `public` таблиц модулей не содержит (ADR-003)."""

    def test_registry_modules(self, registry_modules: list[ModuleDefinition]) -> None:
        """Модули реестра."""
        assert checks.public_schema_violations(registry_modules) == []

    def test_sample_modules(self, sample_report: dict[str, list[str]]) -> None:
        """Модули-образцы скаффолдера."""
        assert sample_report["public_schema"] == []

    def test_table_in_public_schema_is_reported(self, synthetic_module: ModuleDefinition) -> None:
        """Таблица в `public` обнаруживается."""
        assert checks.public_schema_violations([synthetic_module]) == ["rogue: таблица leaked в схеме public"]


@pytest.mark.req("SYS-05-R7")
class TestMandatoryColumnsPresent:
    """У таблиц модулей есть `id uuid` (PK), `created_at`, `updated_at` (`timestamptz`) и `version`."""

    def test_registry_modules(self, registry_modules: list[ModuleDefinition]) -> None:
        """Модули реестра."""
        assert checks.mandatory_column_violations(registry_modules) == []

    @pytest.mark.xfail(
        strict=True,
        reason="Шаблон сущности скаффолдера наследует BaseEntityModel py-main-lib (created_date, без version); "
        "переход на EntityBase shared kernel — этап 1 Г.4 (ADR-003). После Г.4 тест обязан пройти — снять xfail.",
    )
    def test_sample_modules(self, sample_report: dict[str, list[str]]) -> None:
        """Модули-образцы скаффолдера."""
        assert sample_report["mandatory_columns"] == []

    def test_missing_columns_are_reported(self, synthetic_module: ModuleDefinition) -> None:
        """Нехватка колонок обнаруживается; технические таблицы и `__flt_technical__` исключены."""
        violations = checks.mandatory_column_violations([synthetic_module])

        assert violations == [
            "rogue: rogue.bad: created_at не timestamptz (DATETIME)",
            "rogue: rogue.bad: нет колонки version",
            "rogue: public.leaked: id не uuid (VARCHAR)",
            "rogue: public.leaked: нет колонки created_at",
            "rogue: public.leaked: нет колонки updated_at",
            "rogue: public.leaked: нет колонки version",
        ]
