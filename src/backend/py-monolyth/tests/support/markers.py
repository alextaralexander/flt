"""Проверка маркеров pytest при сборе тестов (SYS-10-R12, R29, R30; SYS-05-R45).

Маркеры:
- `ac("<ID ТЗ>-AC<N>")` и `req("SYS-NN-R<M>")` — связь теста с критерием приёмки или требованием;
  хотя бы один обязателен в `tests/modules/`, `tests/n_instances/`, `tests/core/`, `tests/architecture/`,
  архитектурному тесту обязателен `req` (SYS-10-R8, R12);
- `n_instances` — тест стенда N3: только в `tests/n_instances/` и у каждого теста там (SYS-05-R45);
- `smoke` — смоук-набор «ходячего скелета», без аргументов (SYS-10-R31);
- `slow(reason)` — тест длиннее 5 с, обоснование обязательно (SYS-10-R30);
- `quarantine(issue="#123", until="2026-10-24")` — карантин не дольше 14 дней: до `until` падение
  теста не блокирует сборку (`xfail(strict=False)`), после — снова блокирует (SYS-10-R29).

Функции чистые: принимают путь теста относительно корня pytest и список маркеров, поэтому
проверяются unit-тестами без запуска вложенного pytest.
"""

import re
from collections.abc import Iterable
from datetime import date, timedelta

import pytest


ID_RE = re.compile(r"^((VIS|ADM|STU|TCH)-\d{2}(\.\d+)?-AC\d+|SYS-\d{2}-R\d+)$")
TAGGED_DIRS = ("tests/modules/", "tests/n_instances/", "tests/core/", "tests/architecture/")
ARCHITECTURE_DIR = "tests/architecture/"
N_INSTANCES_DIR = "tests/n_instances/"
QUARANTINE_ISSUE_RE = re.compile(r"^(#\d+|OQ-\d{2,})$")
QUARANTINE_MAX_DAYS = 14
TRACE_MARKERS = ("ac", "req")


def marker_errors(rel_path: str, markers: Iterable[pytest.Mark], today: date) -> list[str]:
    """Нарушения правил маркеров у одного теста.

    Args:
        rel_path: Путь файла теста относительно корня pytest (`tests/core/test_ids.py`).
        markers: Все маркеры теста (функции, класса и модуля).
        today: Текущая дата для проверки срока карантина.

    Returns:
        Описания нарушений; пустой список — маркеры корректны.
    """
    marks = list(markers)
    names = {mark.name for mark in marks}
    errors: list[str] = []

    for mark in marks:
        if mark.name in TRACE_MARKERS:
            errors.extend(_trace_marker_errors(mark))
        elif mark.name in ("n_instances", "smoke") and (mark.args or mark.kwargs):
            errors.append(f"маркер {mark.name} не принимает аргументов")
        elif mark.name == "slow" and not _slow_reason(mark):
            errors.append("маркер slow требует обоснования: slow('…') или slow(reason='…') (SYS-10-R30)")
        elif mark.name == "quarantine":
            errors.extend(_quarantine_errors(mark, today))

    if rel_path.startswith(TAGGED_DIRS) and not names & set(TRACE_MARKERS):
        errors.append("нет маркера ac('<ID>-AC<N>') или req('SYS-NN-R<M>') (SYS-10-R12)")
    if rel_path.startswith(ARCHITECTURE_DIR) and "req" not in names:
        errors.append("архитектурный тест без маркера req (SYS-10-R8)")
    in_stand_dir = rel_path.startswith(N_INSTANCES_DIR)
    if in_stand_dir and "n_instances" not in names:
        errors.append("тест в tests/n_instances/ без маркера n_instances (SYS-05-R45)")
    if not in_stand_dir and "n_instances" in names:
        errors.append("маркер n_instances допустим только в tests/n_instances/ (SYS-05-R45)")
    return errors


def quarantine_xfail(markers: Iterable[pytest.Mark], today: date) -> pytest.MarkDecorator | None:
    """`xfail(strict=False)` для теста в действующем карантине, иначе None.

    Args:
        markers: Маркеры теста.
        today: Текущая дата; карантин действует по `until` включительно.

    Returns:
        Маркер, превращающий падение в неблокирующее, или None (карантина нет или он истёк).
    """
    for mark in markers:
        if mark.name != "quarantine":
            continue
        until = _parse_date(mark.kwargs.get("until"))
        if until is not None and today <= until:
            reason = f"карантин {mark.kwargs.get('issue')} до {until.isoformat()} (SYS-10-R29)"
            return pytest.mark.xfail(reason=reason, strict=False)
    return None


def _trace_marker_errors(mark: pytest.Mark) -> list[str]:
    """Маркер ac/req: ровно один позиционный ID нужного формата."""
    if len(mark.args) != 1 or mark.kwargs or not isinstance(mark.args[0], str):
        return [f"маркер {mark.name} принимает один ID строкой: {mark.name}('…') (SYS-10-R12)"]
    value = mark.args[0]
    if not ID_RE.match(value):
        return [f"{mark.name}({value!r}): неверный формат ID (SYS-10-R12)"]
    if mark.name == "ac" and value.startswith("SYS-"):
        return [f"ac({value!r}): требование SYS помечается маркером req (SYS-10-R12)"]
    if mark.name == "req" and not value.startswith("SYS-"):
        return [f"req({value!r}): критерий приёмки помечается маркером ac (SYS-10-R12)"]
    return []


def _slow_reason(mark: pytest.Mark) -> str:
    """Обоснование маркера slow (позиционное или `reason=`)."""
    reason = mark.kwargs.get("reason", mark.args[0] if mark.args else "")
    return reason.strip() if isinstance(reason, str) else ""


def _quarantine_errors(mark: pytest.Mark, today: date) -> list[str]:
    """Маркер quarantine: ссылка на issue или OQ и срок не дальше 14 дней."""
    errors: list[str] = []
    issue = mark.kwargs.get("issue")
    if mark.args or not isinstance(issue, str) or not QUARANTINE_ISSUE_RE.match(issue):
        errors.append("quarantine(issue='#<номер>' или 'OQ-NN', until='YYYY-MM-DD') (SYS-10-R29)")
    until = _parse_date(mark.kwargs.get("until"))
    if until is None:
        errors.append("quarantine: until должен быть датой YYYY-MM-DD (SYS-10-R29)")
    elif until > today + timedelta(days=QUARANTINE_MAX_DAYS):
        errors.append(f"quarantine: until={until.isoformat()} дальше {QUARANTINE_MAX_DAYS} дней (SYS-10-R29)")
    return errors


def _parse_date(value: object) -> date | None:
    """Дата ISO 8601 из аргумента маркера или None."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
