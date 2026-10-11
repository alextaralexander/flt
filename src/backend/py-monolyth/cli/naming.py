"""Утилиты приведения имён к нужным регистрам и проверки имён модулей и топиков."""

import re


# Имя модуля: snake_case, начинается с буквы (оно же имя пакета и схемы PostgreSQL, ADR-002).
MODULE_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
# Имена, которые нельзя использовать как модуль: служебные файлы пакета app.modules и схема public.
RESERVED_MODULE_NAMES = frozenset({"registry", "public", "core", "modules"})
# Топики Kafka (ADR-004, SYS-04): события flt.<module>.<event>.v<N>, задания flt.<module>.jobs.<job>.v<N>.
TOPIC_RE = re.compile(r"^flt\.[a-z][a-z0-9_]*\.(jobs\.)?[a-z][a-z0-9_]*\.v[1-9][0-9]*$")


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


def to_kebab(name: str) -> str:
    """Привести имя к kebab-case (сегменты REST-путей, SYS-03): `llm_gateway` → `llm-gateway`."""
    return to_snake(name).replace("_", "-")


def is_valid_module_name(name: str) -> bool:
    """Имя модуля допустимо: snake_case и не зарезервировано."""
    return bool(MODULE_NAME_RE.match(name)) and name not in RESERVED_MODULE_NAMES


def is_valid_topic(value: str) -> bool:
    """Имя топика соответствует формату ADR-004 / SYS-04."""
    return bool(TOPIC_RE.match(value))
