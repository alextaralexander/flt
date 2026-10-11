"""Общие схемы HTTP-ответов shared kernel (SYS-03-R7, R12, R13, R27).

Конверт ошибки `ErrorResponseV1` объявлен в shared kernel, а не берётся из `py_main_lib`:
он содержит `request_id` и коды ошибок FLT (SYS-03-R7, OQ-69). Поля `INFO` и `WARNING`
сохранены ради совместимости формы, монолит их не заполняет. Общий контракт —
`Analytics/Specs/_system/openapi-common.yaml`; схемы совпадают с его компонентами
`ErrorMessage`, `ErrorResponseV1`, `CoreOffsetPage`, `CoreJobAcceptedResponse` (курсорную страницу
модуль объявляет сам по `CoreCursorPageMeta`, здесь — обобщённая `CorePage`).
"""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ErrorMessage(BaseModel):
    """Описание ошибки: стабильный код, текст для разработчика и детали."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        description="Код ошибки `<module>.<error_name>` (SYS-03-R8); ключ i18n на фронтенде.",
        pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$",
    )
    message: str = Field(description="Текст для разработчика на английском; пользователю не показывается.")
    details: dict[str, Any] = Field(default_factory=dict, description="Детали ошибки (объект).")


class ErrorMessages(BaseModel):
    """Сообщения конверта по уровням; монолит заполняет только `ERROR` ровно одним элементом."""

    model_config = ConfigDict(extra="forbid")

    INFO: list[ErrorMessage] = Field(default_factory=list, max_length=0, description="Не заполняется.")
    WARNING: list[ErrorMessage] = Field(default_factory=list, max_length=0, description="Не заполняется.")
    ERROR: list[ErrorMessage] = Field(min_length=1, max_length=1, description="Ровно одна ошибка.")


class ErrorResponseV1(BaseModel):
    """Конверт ответа 4xx и 5xx монолита на путях `/api/*` (SYS-03-R7)."""

    model_config = ConfigDict(extra="forbid")

    messages: ErrorMessages = Field(description="Сообщения об ошибке.")
    payload: None = Field(default=None, description="Всегда `null`.")
    request_id: str = Field(description="ID запроса (`X-Request-ID`, SYS-03-R20).")


class CorePage[T](BaseModel):
    """Страница коллекции с пагинацией по курсору (SYS-03-R12)."""

    items: list[T] = Field(description="Элементы страницы.")
    next_cursor: str | None = Field(description="Курсор следующей страницы; `null` на последней.")


class CoreOffsetPage[T](BaseModel):
    """Страница административного списка с пагинацией по смещению (SYS-03-R13)."""

    items: list[T] = Field(description="Элементы страницы.")
    total: int = Field(ge=0, description="Общее число элементов.")
    offset: int = Field(ge=0, description="Смещение страницы.")
    limit: int = Field(ge=1, le=100, description="Размер страницы.")


class CoreJobAcceptedResponse(BaseModel):
    """Ответ `202` на запуск фонового задания (SYS-03-R27)."""

    job_id: UUID = Field(description="ID задания; ресурс — `/api/v1/<module>/jobs/{job_id}`.")
    status: Literal["queued"] = Field(default="queued", description="Статус только что созданного задания.")
