import enum


class AssistantNameEnum(enum.StrEnum):
    """Наименование ассистентов."""

    DIALOG = "DIALOG"
    DEVELOPER = "DEVELOPER"
    TESTER = "TESTER"


class TypeTextTemplateEnum(enum.StrEnum):
    """Типы LlmPrompt."""

    SYSTEM = "SYSTEM"
    """Шаблоны этого типа используются для запросов в модель с ролью 'system'."""

    TEMPLATE = "TEMPLATE"
    """Шаблоны этого типа используются для запросов в модель с ролью 'user'."""
