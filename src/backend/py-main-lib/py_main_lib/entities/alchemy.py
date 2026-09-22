"""__init__."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID


class BaseEntityModel:
    """BaseEntity class."""

    __abstract__ = True
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="ID объекта.",
    )
    created_by = Column(
        String,
        nullable=False,
        comment="UUID пользователя, создавшего запись.",
    )
    created_date = Column(DateTime(timezone=True), default=func.now(), nullable=False, comment="Дата создания объекта.")
    last_modified_by = Column(
        String,
        nullable=True,
        comment="UUID пользователя, последним изменившего запись.",
    )
    last_modified_date = Column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
        comment="Дата последнего обновления объекта.",
    )
    is_deleted = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Флаг логического удаления.",
    )
