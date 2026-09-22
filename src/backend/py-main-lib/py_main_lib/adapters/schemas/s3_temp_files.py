from pydantic import BaseModel, Field, field_validator


class S3TempFilesConfig(BaseModel):
    """Настройки для временных файлов индексатора в S3."""

    temp_bucket_name: str = Field(..., description="Имя S3 бакета для временных файлов")
    temp_files_prefix: str = Field(default="temp-files/rag-indexer/", description="Префикс для временных файлов")
    s3_retry_attempts: int = Field(default=3, ge=1, le=10, description="Количество повторов для S3 операций")
    immediate_cleanup: bool = Field(default=True, description="Удалять временные файлы сразу после обработки")

    @field_validator("temp_files_prefix")
    @classmethod
    def normalize_prefix(cls, value: str) -> str:
        normalized = value.lstrip("/")
        if normalized and not normalized.endswith("/"):
            normalized += "/"
        return normalized

    def build_source_prefix(self, source_id: str) -> str:
        """Возвращает префикс каталога для конкретного источника."""
        safe_source = (source_id or "unknown").replace("/", "_").replace("\\", "_")
        return f"{self.temp_files_prefix}source_{safe_source}/"
