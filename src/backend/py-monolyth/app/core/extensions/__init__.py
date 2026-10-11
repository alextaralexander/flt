"""Точки расширения shared kernel (SYS-09-R1–R3): объявление, вклады, реестр через контейнер."""

from app.core.extensions.point import ExtensionContribution, ExtensionPoint
from app.core.extensions.registry import (
    ExtensionRegistrationError,
    ExtensionRegistry,
    build_extension_registries,
    provide_registry,
    register_extension_registries,
)


__all__ = (
    "ExtensionContribution",
    "ExtensionPoint",
    "ExtensionRegistrationError",
    "ExtensionRegistry",
    "build_extension_registries",
    "provide_registry",
    "register_extension_registries",
)
