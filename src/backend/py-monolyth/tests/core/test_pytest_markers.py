"""Тесты правил маркеров pytest (SYS-10-R12, R29, R30; SYS-05-R45)."""

from datetime import date

import pytest

from tests.support.markers import marker_errors, quarantine_xfail


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-10-R12")]

TODAY = date(2026, 10, 11)
CORE_TEST = "tests/core/test_x.py"


def marks(*decorators: pytest.MarkDecorator) -> list[pytest.Mark]:
    """Маркеры теста из декораторов `pytest.mark.*`."""
    return [decorator.mark for decorator in decorators]


class TestTraceMarkers:
    """`ac` и `req`: обязательны в каталогах с трассировкой, формат ID проверяется."""

    @pytest.mark.parametrize(
        "decorator",
        [
            pytest.mark.ac("STU-18-AC3"),
            pytest.mark.ac("VIS-04.1-AC12"),
            pytest.mark.req("SYS-05-R12"),
        ],
    )
    def test_valid_ids_are_accepted(self, decorator: pytest.MarkDecorator) -> None:
        """Корректные ID критерия и требования проходят."""
        # - Act / Assert -
        assert marker_errors(CORE_TEST, marks(decorator), TODAY) == []

    @pytest.mark.parametrize(
        ("decorator", "message"),
        [
            (pytest.mark.ac("STU-18"), "неверный формат"),
            (pytest.mark.req("SYS-5-R1"), "неверный формат"),
            (pytest.mark.ac("SYS-05-R1"), "маркером req"),
            (pytest.mark.req("STU-18-AC3"), "маркером ac"),
            (pytest.mark.req("SYS-05-R1", "SYS-05-R2"), "один ID"),
            (pytest.mark.ac(id="STU-18-AC3"), "один ID"),
        ],
    )
    def test_invalid_ids_are_reported(self, decorator: pytest.MarkDecorator, message: str) -> None:
        """Неверный формат, перепутанный маркер или лишние аргументы — ошибка."""
        # - Act -
        errors = marker_errors(CORE_TEST, marks(decorator), TODAY)

        # - Assert -
        assert len(errors) == 1
        assert message in errors[0]

    @pytest.mark.parametrize(
        "rel_path",
        ["tests/core/x/test_a.py", "tests/modules/identity/unit/test_a.py", "tests/architecture/test_a.py"],
    )
    def test_traced_dirs_require_marker(self, rel_path: str) -> None:
        """Тест в каталогах трассировки без `ac`/`req` — ошибка сбора."""
        # - Act -
        errors = marker_errors(rel_path, [], TODAY)

        # - Assert -
        assert any("нет маркера ac" in error for error in errors)

    def test_other_dirs_do_not_require_marker(self) -> None:
        """Скаффолдер и настройки (`tests/cli`, `tests/configs`) маркер не требуют."""
        # - Act / Assert -
        assert marker_errors("tests/cli/test_scaffolder.py", [], TODAY) == []

    def test_architecture_requires_req(self) -> None:
        """Архитектурный тест обязан нести `req`, `ac` недостаточно (SYS-10-R8)."""
        # - Act -
        errors = marker_errors("tests/architecture/test_a.py", marks(pytest.mark.ac("STU-18-AC3")), TODAY)

        # - Assert -
        assert errors == ["архитектурный тест без маркера req (SYS-10-R8)"]


@pytest.mark.req("SYS-05-R45")
class TestNInstancesMarker:
    """`n_instances` — только в `tests/n_instances/` и обязателен там."""

    def test_stand_test_without_marker_is_reported(self) -> None:
        """Тест стенда без `n_instances` — ошибка."""
        # - Act -
        errors = marker_errors("tests/n_instances/core/test_a.py", marks(pytest.mark.req("SYS-05-R44")), TODAY)

        # - Assert -
        assert errors == ["тест в tests/n_instances/ без маркера n_instances (SYS-05-R45)"]

    def test_marker_outside_stand_dir_is_reported(self) -> None:
        """`n_instances` вне каталога стенда — ошибка."""
        # - Act -
        errors = marker_errors(CORE_TEST, marks(pytest.mark.n_instances, pytest.mark.req("SYS-05-R44")), TODAY)

        # - Assert -
        assert errors == ["маркер n_instances допустим только в tests/n_instances/ (SYS-05-R45)"]

    def test_stand_test_with_markers_is_accepted(self) -> None:
        """Тест стенда с `n_instances` и `req` корректен."""
        # - Act / Assert -
        stand_marks = marks(pytest.mark.n_instances, pytest.mark.smoke, pytest.mark.req("SYS-05-R52"))
        assert marker_errors("tests/n_instances/core/test_a.py", stand_marks, TODAY) == []

    @pytest.mark.parametrize("decorator", [pytest.mark.n_instances(3), pytest.mark.smoke("x")])
    def test_flags_take_no_arguments(self, decorator: pytest.MarkDecorator) -> None:
        """`n_instances` и `smoke` — флаги без аргументов."""
        # - Act -
        errors = marker_errors("tests/n_instances/core/test_a.py", [*marks(decorator), *_stand_marks()], TODAY)

        # - Assert -
        assert any("не принимает аргументов" in error for error in errors)


@pytest.mark.req("SYS-10-R30")
class TestSlowMarker:
    """`slow` требует обоснования."""

    def test_slow_without_reason_is_reported(self) -> None:
        """`slow` без причины — ошибка."""
        # - Act -
        errors = marker_errors(CORE_TEST, marks(pytest.mark.slow, pytest.mark.req("SYS-05-R1")), TODAY)

        # - Assert -
        assert errors and "обоснования" in errors[0]

    @pytest.mark.parametrize("decorator", [pytest.mark.slow("argon2id"), pytest.mark.slow(reason="25 000 строк")])
    def test_slow_with_reason_is_accepted(self, decorator: pytest.MarkDecorator) -> None:
        """Причина — позиционная или `reason=`."""
        # - Act / Assert -
        assert marker_errors(CORE_TEST, [*marks(decorator), *marks(pytest.mark.req("SYS-05-R1"))], TODAY) == []


@pytest.mark.req("SYS-10-R29")
class TestQuarantineMarker:
    """`quarantine(issue, until)`: не дольше 14 дней, до `until` падение не блокирует."""

    def test_active_quarantine_turns_failure_into_xfail(self) -> None:
        """В пределах срока тест получает `xfail(strict=False)`."""
        # - Arrange -
        quarantine = marks(pytest.mark.quarantine(issue="#142", until="2026-10-24"))

        # - Act -
        decorator = quarantine_xfail(quarantine, TODAY)

        # - Assert -
        assert marker_errors(CORE_TEST, [*quarantine, *_trace()], TODAY) == []
        assert decorator is not None
        assert decorator.mark.name == "xfail"
        assert decorator.mark.kwargs["strict"] is False

    def test_expired_quarantine_blocks_again(self) -> None:
        """После `until` карантин не действует: падение снова блокирует сборку."""
        # - Act / Assert -
        assert quarantine_xfail(marks(pytest.mark.quarantine(issue="#142", until="2026-10-10")), TODAY) is None

    def test_no_quarantine_no_xfail(self) -> None:
        """Без маркера карантина xfail не добавляется."""
        # - Act / Assert -
        assert quarantine_xfail(_trace(), TODAY) is None

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"issue": "#142", "until": "2026-11-30"}, "дальше 14 дней"),
            ({"issue": "flaky", "until": "2026-10-20"}, "issue="),
            ({"issue": "OQ-31", "until": "soon"}, "YYYY-MM-DD"),
        ],
    )
    def test_invalid_quarantine_is_reported(self, kwargs: dict[str, str], message: str) -> None:
        """Карантин дольше 14 дней, без ссылки на issue/OQ или без даты — ошибка."""
        # - Act -
        errors = marker_errors(CORE_TEST, [*marks(pytest.mark.quarantine(**kwargs)), *_trace()], TODAY)

        # - Assert -
        assert any(message in error for error in errors)


def _trace() -> list[pytest.Mark]:
    """Корректный маркер требования для тестов, проверяющих другие маркеры."""
    return marks(pytest.mark.req("SYS-10-R29"))


def _stand_marks() -> list[pytest.Mark]:
    """Маркеры корректного теста стенда N3."""
    return marks(pytest.mark.n_instances, pytest.mark.req("SYS-05-R44"))
