"""Пользователи, учётные данные и роли модуля `identity` (ADR-006, раздел 3.1; спецификация модуля, 5.1)."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.dao.db_helpers.base import EntityBase
from app.modules.identity.models import Base


class UserStatus(StrEnum):
    """Статус учётной записи."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class User(EntityBase, Base):
    """Пользователь платформы (email может отсутствовать у входа только через OAuth)."""

    __tablename__ = "users"

    email: Mapped[str | None] = mapped_column(CITEXT, unique=True, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=UserStatus.ACTIVE.value)
    ui_language: Mapped[str] = mapped_column(String(8), nullable=False, default="ru")
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="UTC")


class Credential(EntityBase, Base):
    """Пароль пользователя (argon2id) и счётчик неудачных входов."""

    __tablename__ = "credentials"

    user_id: Mapped[UUID] = mapped_column(nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    password_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Role(EntityBase, Base):
    """Код роли: `learner`, `teacher`, `platform_admin` (SYS-06-R1)."""

    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)


class UserRole(EntityBase, Base):
    """Назначение роли пользователю; отзыв — `revoked_at` (SYS-06-R11)."""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_code", "granted_at"),)

    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    role_code: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    granted_by: Mapped[UUID | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
