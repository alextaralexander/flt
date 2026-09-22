"""Утилиты приведения имён к нужным регистрам."""

import re


def to_snake(name: str) -> str:
    """Привести имя к snake_case.

    :param name: Имя в любом регистре (`Order`, `OrderItem`, `ORDER_CREATED`).
    :return: Имя в snake_case (`order`, `order_item`, `order_created`).
    """
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    s3 = re.sub(r"[\s\-]+", "_", s2)
    return re.sub(r"_+", "_", s3).strip("_").lower()


def to_pascal(name: str) -> str:
    """Привести имя к PascalCase.

    :param name: Имя в любом регистре.
    :return: Имя в PascalCase (`Order`, `OrderItem`, `OrderCreated`).
    """
    parts = [p for p in to_snake(name).split("_") if p]
    return "".join(part.capitalize() for part in parts)


def to_const(name: str) -> str:
    """Привести имя к CONSTANT_CASE (для enum-членов)."""
    return to_snake(name).upper()
