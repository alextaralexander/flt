"""Универсальные схемы для контента от всех адаптеров."""

from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class UniversalDocument(BaseModel):
    """Универсальный документ от любого адаптера."""

    source_identifier: str = Field(..., description="Уникальное имя источника")
    content: str = Field(..., description="Текстовое содержимое для индексации")
    resource_type: str = Field(..., description="Тип ресурса: file, page, issue, etc")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные источника")


class UniversalContentResponse(BaseModel):
    """Универсальный ответ от адаптеров с контентом."""

    source_id: str = Field(..., description="ID источника в системе RAG")
    source_type: str = Field(..., description="Тип адаптера: samba, confluence, jira, etc")
    documents: List[UniversalDocument] = Field(..., description="Список документов для индексации")
    total_processed: int = Field(..., description="Количество обработанных документов")
    # Опциональные поля для батчинга: позволяют маркировать финальный батч без изменения старых продюсеров
    total_files: int | None = Field(default=None, description="Общее количество файлов в источнике")
    is_last_batch: bool | None = Field(default=None, description="Флаг финального батча")
    failed_count: int = Field(default=0, description="Количество неудачных обработок")
    processing_errors: List[str] = Field(default_factory=list, description="Ошибки обработки")
    processed_at: datetime = Field(default_factory=datetime.utcnow, description="Время обработки")
