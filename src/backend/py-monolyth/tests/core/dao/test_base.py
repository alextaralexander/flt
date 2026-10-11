"""Тесты декларативных баз модулей (`make_module_base`, `module_metadata`)."""

import pytest
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.dao.db_helpers.base import NAMING_CONVENTION, make_module_base, module_metadata


pytestmark = pytest.mark.no_db


class TestMakeModuleBase:
    """Таблицы модуля живут в схеме модуля (ADR-002, раздел 3.4)."""

    def test_tables_get_module_schema(self) -> None:
        """Модель, унаследованная от базы модуля, попадает в схему модуля без `__table_args__`."""
        # - Arrange -
        base = make_module_base("sample_mod")

        class Sample(base):  # type: ignore[valid-type,misc]
            """Модель для проверки схемы."""

            __tablename__ = "samples"

            id: Mapped[str] = mapped_column(String, primary_key=True)

        # - Act -
        table = Sample.__table__

        # - Assert -
        assert table.schema == "sample_mod"
        assert base.metadata.naming_convention == NAMING_CONVENTION

    def test_bases_do_not_share_metadata(self) -> None:
        """У каждого модуля свои метаданные — модели модулей не смешиваются."""
        # - Act -
        first, second = make_module_base("first_mod"), make_module_base("second_mod")

        # - Assert -
        assert first.metadata is not second.metadata

    @pytest.mark.parametrize("schema", ["", "public", "bad-name", "1abc"])
    def test_invalid_schema_is_rejected(self, schema: str) -> None:
        """Пустая схема, `public` и не-идентификаторы запрещены (схема `public` без таблиц, ADR-003)."""
        # - Act / Assert -
        with pytest.raises(ValueError):
            module_metadata(schema)
