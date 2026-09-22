"""Утилита для создания цветных логгеров с тегами."""

import inspect
import json
import logging
from functools import partial
from typing import Any, Mapping, Protocol, cast

import colorlog


class LogMethod(Protocol):
    """Протокол для методов логирования"""

    def __call__(self, msg: str, data: Any = None) -> None:
        pass


# Теги, цвета, можно добавить свои
DEFAULT_COLORS = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
    "orange": "\033[38;5;208m",
    "purple": "\033[38;5;141m",
    "ocean": "\033[38;5;45m",
}

DEFAULT_TAGS = {
    # Для Входящих / Исходящих Kafka сообщений
    "incoming": "INCOMING",
    "outgoing": "OUTGOING",
    "success": "SUCCESS",
    "error": "ERROR",
    "warning": "WARNING",
    "info": "INFO",
    "debug": "DEBUG",
    "api": "API",
    "database": "DATABASE",
    "cache": "CACHE",
    "event": "EVENT",
    "metric": "METRIC",
    "security": "SECURITY",
    "config": "CONFIG",
    "model": "MODEL",
}

RESET_CODE = "\033[0m"


class TaggedColorLogger:
    """Вспомогательный класс для поддержки цепочек вызовов типа logger.yellow.outgoing()"""

    def __init__(
        self, logger: logging.LoggerAdapter, color_code: str, color_name: str, tags: dict[str, str] | None = None
    ):
        self.logger = logger
        self.color_code = color_code
        self.color_name = color_name
        self.tags = {**DEFAULT_TAGS, **(tags or {})}

        # Динамически создаем методы для тегов
        for tag_name, tag_label in self.tags.items():
            setattr(self, tag_name, partial(self._log_with_tag, tag_label))

    def __call__(self, msg: str, data: Any = None) -> None:
        """Позволяет использовать logger.yellow(msg) без тега"""
        formatted_message = self._format_message(msg, data)
        self.logger.info(f"{self.color_code}{formatted_message}{RESET_CODE}")

    def _log_with_tag(self, tag: str, msg: str, data: Any = None) -> None:
        """Логирует сообщение с цветом и тегом"""
        formatted_message = self._format_message(msg, data)
        self.logger.info(f"{self.color_code}[{tag}] {formatted_message}{RESET_CODE}")

    def _format_message(self, msg: str, data: Any) -> str:
        """Форматирует сообщение с данными"""
        if data is not None:
            return f"{msg}{ColoredLogger.format_json(data)}"
        return msg

    # Объявляем методы для IDE
    incoming: LogMethod
    outgoing: LogMethod
    success: LogMethod
    error: LogMethod
    warning: LogMethod
    info: LogMethod
    debug: LogMethod
    api: LogMethod
    database: LogMethod
    cache: LogMethod
    event: LogMethod
    metric: LogMethod
    security: LogMethod
    config: LogMethod
    model: LogMethod


class TaggedStandardLogger:
    """Вспомогательный класс для поддержки тегов со стандартными уровнями логирования"""

    def __init__(
        self,
        logger: logging.LoggerAdapter,
        log_method_name: str,
        tags: Mapping[str, str] | None = None,
    ):
        self.logger = logger
        self.log_method_name = log_method_name
        self.tags = {**DEFAULT_TAGS, **(dict(tags) if tags is not None else {})}

        # Динамически создаем методы для тегов
        for tag_name, tag_label in self.tags.items():
            setattr(self, tag_name, partial(self._log_with_tag, tag_label))

    def __call__(self, msg: str, *args, **kwargs) -> None:
        """Стандартный вызов без тега - используем оригинальный метод LoggerAdapter"""
        original_method = getattr(logging.LoggerAdapter, self.log_method_name)
        original_method(self.logger, msg, *args, **kwargs)

    def _log_with_tag(self, tag: str, msg: str, *args, **kwargs) -> None:
        """Логирует сообщение с тегом"""
        tagged_message = f"[{tag}] {msg}"
        # Получаем оригинальный метод
        original_method = getattr(logging.LoggerAdapter, self.log_method_name)
        original_method(self.logger, tagged_message, *args, **kwargs)

    # Объявляем методы для IDE
    incoming: LogMethod
    outgoing: LogMethod
    success: LogMethod
    error: LogMethod
    warning: LogMethod
    info: LogMethod
    debug: LogMethod
    api: LogMethod
    database: LogMethod
    cache: LogMethod
    event: LogMethod
    metric: LogMethod
    security: LogMethod
    config: LogMethod
    model: LogMethod


class ColoredLogger(logging.LoggerAdapter):
    """Расширенный логгер с поддержкой 10 цветов и тегов."""

    def __init__(
        self,
        logger: logging.Logger,
        extra: dict[str, Any] | None = None,
        custom_colors: dict[str, str] | None = None,
        custom_tags: dict[str, str] | None = None,
    ):
        super().__init__(logger, extra or {})

        # Объединяем дефолтные и кастомные цвета/теги
        self.colors = {**DEFAULT_COLORS, **(custom_colors or {})}
        self.tags = {**DEFAULT_TAGS, **(custom_tags or {})}

        # Динамически создаем методы для каждого цвета
        for color_name, color_code in self.colors.items():
            tagged_logger = TaggedColorLogger(self, color_code, color_name, self.tags)
            setattr(self, color_name, tagged_logger)

        # Оборачиваем стандартные методы логирования для поддержки тегов
        cast(Any, self).debug = TaggedStandardLogger(self, "debug", self.tags)
        cast(Any, self).info = TaggedStandardLogger(self, "info", self.tags)
        cast(Any, self).warning = TaggedStandardLogger(self, "warning", self.tags)
        cast(Any, self).error = TaggedStandardLogger(self, "error", self.tags)
        cast(Any, self).critical = TaggedStandardLogger(self, "critical", self.tags)

    @staticmethod
    def format_json(data: Any) -> str:
        """Форматирует JSON или объект для вывода в логи."""
        try:
            if isinstance(data, dict):
                return "\n" + json.dumps(data, indent=2, ensure_ascii=False, default=str)
            elif hasattr(data, "model_dump"):
                # Для объектов Pydantic
                return "\n" + json.dumps(data.model_dump(), indent=2, ensure_ascii=False, default=str)
            elif hasattr(data, "__dict__"):
                # Для других объектов пробуем преобразовать их атрибуты
                return "\n" + json.dumps(vars(data), indent=2, ensure_ascii=False, default=str)
            return f" {data}"
        except Exception as e:
            return f" [Ошибка форматирования: {e}]"

    # Обратная совместимость (для моего сервиса)
    def incoming(self, msg: str, data: Any = None) -> None:
        """Логирует входящие сообщения желтым цветом."""
        getattr(self, "yellow").incoming(msg, data)

    def outgoing(self, msg: str, data: Any = None) -> None:
        """Логирует исходящие сообщения оранжевым цветом."""
        getattr(self, "orange").outgoing(msg, data)

    def success(self, msg: str, data: Any = None) -> None:
        """Логирует успешные операции зеленым цветом."""
        getattr(self, "green").success(msg, data)

    def model_settings(self, msg: str, data: Any = None) -> None:
        """Логирует настройки модели океанским цветом."""
        getattr(self, "ocean").model(msg, data)


def get_colored_logger(
    name: str | None = None,
    level: int | None = None,
    custom_colors: dict[str, str] | None = None,
    custom_tags: dict[str, str] | None = None,
) -> ColoredLogger:
    """Создает и настраивает цветной логгер."""

    if name is None:
        frame = inspect.currentframe()
        try:
            caller_frame = frame.f_back if frame is not None else None
            caller_module = caller_frame.f_globals.get("__name__", "root") if caller_frame is not None else "root"
            name = caller_module
        except Exception:
            name = "root"
        finally:
            del frame

    base_logger = logging.getLogger(name)

    if level is not None:
        base_logger.setLevel(level)
    elif not base_logger.handlers:
        base_logger.setLevel(logging.INFO)

    if base_logger.handlers:
        return ColoredLogger(base_logger, custom_colors=custom_colors, custom_tags=custom_tags)

    formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s - %(name)s - %(levelname)s%(reset)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        reset=True,
        log_colors={
            "DEBUG": "white",
            "INFO": "white",
            "WARNING": "white",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
        secondary_log_colors={},
        style="%",
    )

    handler = colorlog.StreamHandler()
    handler.setFormatter(formatter)

    base_logger.addHandler(handler)
    base_logger.propagate = False

    return ColoredLogger(base_logger, custom_colors=custom_colors, custom_tags=custom_tags)


# Пример использования
if __name__ == "__main__":
    logger = get_colored_logger()

    # Стандартные методы работают как обычно
    logger.info("Обычное информационное сообщение")
    logger.warning("Обычное предупреждение")
    logger.error("Обычная ошибка")
    logger.debug("Обычная ошибка")
    logger.critical("Критическая ошибка")

    # Стандартные методы с тегами
    getattr(logger.info, "database")("Запрос к БД")
    getattr(logger.warning, "api")("Медленный API запрос")
    getattr(logger.error, "security")("Проблема безопасности")

    # Цветные сообщения
    getattr(logger, "cyan")("Голубое сообщение")
    getattr(logger, "red")("Красное сообщение")

    # Цветные сообщения с тегами
    getattr(logger, "red").database("Ошибка БД")
    getattr(logger, "green").success("Операция завершена")
    getattr(logger, "orange").outgoing("Отправка данных")

    # Пример с кастомными цветами и тегами
    custom_logger = get_colored_logger(
        "custom", custom_colors={"pink": "\033[38;5;213m"}, custom_tags={"custom_tag": "CUSTOM"}
    )
    getattr(custom_logger, "pink").custom_tag("Кастомное сообщение")
