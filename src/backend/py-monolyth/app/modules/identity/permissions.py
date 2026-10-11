"""Права модуля `identity`: коды `identity:<resource>:<action>` (SYS-06, ADR-002).

Классы `<Resource>Permissions` добавляет `make scaffold-entity module=identity name=<Entity>` (ниже).
"""

import sys


def module_permissions() -> tuple[str, ...]:
    """Все коды прав модуля: строковые константы классов `*Permissions` этого файла."""
    codes = {
        value
        for holder_name, holder in vars(sys.modules[__name__]).items()
        if holder_name.endswith("Permissions") and isinstance(holder, type)
        for attr, value in vars(holder).items()
        if attr.isupper() and isinstance(value, str)
    }
    return tuple(sorted(codes))
