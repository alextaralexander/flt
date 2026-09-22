from datetime import datetime
from typing import Any, Dict, List, Sequence

from pydantic import BaseModel, Field, field_validator, model_validator


class BaseS3FileReference(BaseModel):
    """Базовая ссылка на временный файл в S3."""

    s3_key: str = Field(..., description="Ключ файла в S3 temp-bucket")
    source_identifier: str = Field(..., description="Идентификатор исходного файла")
    content_size: int = Field(..., ge=0, description="Размер контента в байтах")
    file_metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные файла")
    uploaded_at: datetime = Field(default_factory=datetime.utcnow, description="Время загрузки в S3")

    @field_validator("s3_key")
    @classmethod
    def validate_s3_key(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("s3_key must be provided")
        normalized = value.lstrip("/")
        if "/" not in normalized:
            raise ValueError("s3_key must contain a prefix path")
        return normalized


class SambaFileReference(BaseS3FileReference):
    """Ссылка на файл из Samba адаптера."""


class S3FileReference(BaseS3FileReference):
    """Ссылка на файл из S3 адаптера."""


class BaseS3ContentMessage(BaseModel):
    """Общий формат сообщений с батчем ссылок на S3 файлы."""

    source_id: str = Field(..., description="ID источника RAG")
    source_type: str = Field(..., description="Тип адаптера")
    file_references: Sequence[BaseS3FileReference] = Field(default_factory=list, description="Ссылки на файлы в S3")
    total_files: int = Field(..., ge=0, description="Общее количество файлов (0 для error-only сообщений)")
    processed_files: int = Field(..., ge=0, description="Количество обработанных файлов")
    failed_files: int = Field(default=0, ge=0, description="Количество файлов с ошибками")
    processing_errors: Sequence[str] = Field(default_factory=list, description="Ошибки обработки")
    is_final_batch: bool = Field(default=False, description="Флаг финального батча")
    batch_number: int = Field(default=1, ge=1, description="Номер батча, начиная с 1")

    @model_validator(mode="after")
    def validate_counts(self):
        # Разрешаем пустой батч только если есть ошибки (error-only message)
        if not self.file_references and not self.processing_errors:
            raise ValueError("file_references или processing_errors должны быть заполнены")
        if self.processed_files + self.failed_files > self.total_files and self.total_files > 0:
            raise ValueError("processed_files + failed_files не могут превышать total_files")
        if len(self.file_references) > self.total_files and self.total_files > 0:
            raise ValueError("Количество ссылок не может превышать total_files")
        return self


class SambaS3ContentMessage(BaseS3ContentMessage):
    """Сообщение с батчем файлов из Samba адаптера."""

    source_type: str = Field(default="samba", description="Тип адаптера")
    file_references: List[SambaFileReference] = Field(default_factory=list)


class S3AdapterS3ContentMessage(BaseS3ContentMessage):
    """Сообщение с батчем файлов из S3 адаптера."""

    source_type: str = Field(default="s3", description="Тип адаптера")
    file_references: List[S3FileReference] = Field(default_factory=list)
