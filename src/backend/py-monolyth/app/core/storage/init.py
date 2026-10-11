"""Инициализация хранилища ролью `migrate`: бакеты `flt-<module>` модулей с `storage=True` (ADR-007, 3.6)."""

from collections.abc import Sequence

from app.core.modules import ModuleDefinition
from app.core.storage.file_storage import FileStorage, bucket_name
from configs.storage_config import storage_settings


def module_buckets(modules: Sequence[ModuleDefinition]) -> list[str]:
    """Бакеты модулей, объявивших `storage=True`, в порядке реестра."""
    return [bucket_name(module.name) for module in modules if module.storage]


async def init_storage(modules: Sequence[ModuleDefinition], storage: FileStorage | None = None) -> list[str]:
    """Идемпотентно создаёт бакеты модулей; без модулей с файлами хранилище не требуется.

    Returns:
        Созданные бакеты.
    """
    buckets = module_buckets(modules)
    if not buckets:
        return []
    client = storage or FileStorage(storage_settings())
    return await client.ensure_buckets(buckets)
