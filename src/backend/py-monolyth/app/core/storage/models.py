"""Миксин метаданных файла `StoredFileMixin` и статусы `file_status` (ADR-007, раздел 3.2; SYS-05-R9).

Каждый модуль с файлами объявляет свою таблицу на `EntityBase` + `StoredFileMixin` в своей
схеме и миграции; `id` сущности совпадает с `<file_id>` в ключе объекта.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class FileStatus(StrEnum):
    """Жизненный цикл файла: `pending` → `uploaded` → `processing` → `ready` → `deleted`."""

    PENDING = "pending"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    DELETED = "deleted"


class StoredFileMixin:
    """Обязательные колонки метаданных файла (уникальность `bucket` + `key` задаёт таблица модуля)."""

    bucket: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_user_id: Mapped[UUID | None] = mapped_column(nullable=True)
    original_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=FileStatus.PENDING.value)
    multipart_upload_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def object_key(owner_user_id: UUID | None, file_id: UUID, filename_ext: str = "") -> str:
    """Ключ объекта: `u/<owner_user_id>/<file_id><ext>` или `public/<file_id><ext>` у медиа платформы."""
    head = f"u/{owner_user_id}" if owner_user_id is not None else "public"
    return f"{head}/{file_id}{filename_ext}"
