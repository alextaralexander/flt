"""Точка входа образа `flt-backend`: `python -m app` запускает процесс роли `APP_ROLE` (ADR-004, раздел 3.5).

| Роль | Что запускается | Порт |
|---|---|---|
| `api` | uvicorn: REST, служебные `/v1/*`, документация `/api/docs` | `FAST_API_PORT` (8000) |
| `worker` | `AsgiFastStream`: консьюмеры Kafka, `/v1/*`, `/asyncapi/kafka` | `WORKER_HTTP_PORT` (8001) |
| `all` | `api` и брокер `worker` в одном процессе (только local и pytest) | `FAST_API_PORT` |
| `migrate` | `alembic -n <module> upgrade head` по модулям реестра, затем выход 0 | — |
| `media_agent` | AI-преподаватель в LiveKit — этап 6 (ADR-015); сейчас выход с ошибкой | — |

`python -m app healthcheck` — проверка `/v1/health` на порту роли (HEALTHCHECK Docker-образа).
Миграции инстансами при старте не выполняются: это отдельный шаг роли `migrate` (ADR-003).
Роль `migrate` также создаёт топики Kafka и их DLQ по декларациям модулей; `storage-init` и шаблоны
индексов она получает вместе с хранилищем и поиском (этап 1 Г.4).
"""

import argparse
import asyncio
import json
import socket
import sys
import urllib.request
from collections.abc import Sequence
from datetime import datetime

import uvicorn
from alembic import command
from alembic.config import Config

from app.core.kafka.dlq import DlqReplayLimitError, list_dlq, replay_dlq
from app.core.kafka.topics_admin import apply_topics
from app.core.logging import app_logger, logger_settings
from app.core.modules import load_modules
from app.core.storage.init import init_storage
from app.core.ws.hub import WsHub
from app.main import create_app, create_worker_app
from app.modules.registry import MODULES
from configs.settings import AppRole, settings


ALEMBIC_INI = "alembic.ini"
HEALTHCHECK_TIMEOUT_SECONDS = 3
# Роли со служебным HTTP на WORKER_HTTP_PORT (ADR-004, ADR-010).
WORKER_PORT_ROLES = frozenset({AppRole.WORKER, AppRole.MEDIA_AGENT})


class ApiServer(uvicorn.Server):
    """uvicorn роли `api`: при остановке сначала закрывает `/ws` кодом 1012 `instance_shutdown`.

    Сам uvicorn при SIGTERM закрывает WebSocket кодом 1012 без причины ещё до lifespan shutdown;
    хаб закрывает соединения раньше, с причиной из таблицы SYS-04-R10 (SYS-04-R18, SYS-05-R26).
    """

    def __init__(self, config: uvicorn.Config, hub: WsHub | None) -> None:
        """Сервер с хабом WebSocket приложения."""
        super().__init__(config)
        self.hub = hub

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        """Закрытие соединений хаба, затем штатная остановка uvicorn."""
        if self.hub is not None:
            await self.hub.stop()
        await super().shutdown(sockets)


def run_api(role: AppRole) -> None:
    """Запускает HTTP-приложение (роли `api` и `all`) за HAProxy: доверие X-Forwarded-* (ADR-012)."""
    application = create_app(role=role)
    config = uvicorn.Config(
        application,
        host=settings.FAST_API_HOST,
        port=settings.FAST_API_PORT,
        proxy_headers=True,
        forwarded_allow_ips=settings.FORWARDED_ALLOW_IPS,
        timeout_graceful_shutdown=settings.SHUTDOWN_GRACE_SECONDS,
        log_config=None,
    )
    ApiServer(config, getattr(application.state, "ws_hub", None)).run()


def run_worker() -> None:
    """Запускает роль `worker`: консьюмеры Kafka модулей и служебный HTTP на `WORKER_HTTP_PORT`."""
    uvicorn.run(
        create_worker_app(),
        host=settings.FAST_API_HOST,
        port=settings.WORKER_HTTP_PORT,
        timeout_graceful_shutdown=settings.SHUTDOWN_GRACE_SECONDS,
        log_config=None,
    )


def run_migrations(modules: Sequence[str] = MODULES) -> None:
    """Роль `migrate`: миграции Alembic каждого модуля реестра по порядку (как `make migrate`)."""
    for module in modules:
        app_logger.info("Миграции модуля", module=module)
        command.upgrade(Config(ALEMBIC_INI, ini_section=module), "head")
    app_logger.info("Миграции завершены", modules=len(modules))


def run_migrate(modules: Sequence[str] = MODULES) -> None:
    """Роль `migrate`: миграции модулей, топики Kafka и их DLQ (SYS-04-R23), бакеты хранилища (ADR-007)."""
    run_migrations(modules)
    definitions = load_modules(modules)
    declarations = [topic for module in definitions for topic in module.topics]
    created = asyncio.run(apply_topics(declarations))
    app_logger.info("Топики Kafka готовы", declared=len(declarations), created=len(created))
    buckets = asyncio.run(init_storage(definitions))
    app_logger.info("Хранилище готово", created=len(buckets))


def run_dlq(args: Sequence[str]) -> int:
    """`dlq list|replay`: разбор dead letter topic вручную (SYS-04-R28)."""
    parser = argparse.ArgumentParser(prog="python -m app dlq")
    commands = parser.add_subparsers(dest="command", required=True)
    list_parser = commands.add_parser("list", help="Сообщения <topic>.dlq")
    list_parser.add_argument("--topic", required=True)
    list_parser.add_argument("--since", type=datetime.fromisoformat, default=None)
    replay_parser = commands.add_parser("replay", help="Вернуть сообщения <topic>.dlq в <topic>")
    replay_parser.add_argument("--topic", required=True)
    replay_parser.add_argument("--event-id", dest="event_ids", action="append", default=None)
    replay_parser.add_argument("--consumer", default=None)
    replay_parser.add_argument("--dry-run", action="store_true")
    replay_parser.add_argument("--force", action="store_true")
    options = parser.parse_args(list(args))
    if options.command == "list":
        for entry in asyncio.run(list_dlq(options.topic, since=options.since)):
            print(json.dumps(entry, ensure_ascii=False))
        return 0
    try:
        replayed = asyncio.run(
            replay_dlq(
                options.topic,
                event_ids=options.event_ids,
                consumer=options.consumer,
                dry_run=options.dry_run,
                force=options.force,
            )
        )
    except DlqReplayLimitError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"replayed": replayed, "dry_run": options.dry_run}, ensure_ascii=False))
    return 0


def healthcheck(role: AppRole) -> int:
    """Код возврата проверки `/v1/health` на порту роли; у ролей без HTTP проверять нечего (0)."""
    if role is AppRole.MIGRATE:
        return 0
    port = settings.WORKER_HTTP_PORT if role in WORKER_PORT_ROLES else settings.FAST_API_PORT
    url = f"http://127.0.0.1:{port}/v1/health"
    try:
        # Фиксированный локальный адрес, схема http.
        with urllib.request.urlopen(url, timeout=HEALTHCHECK_TIMEOUT_SECONDS) as response:  # nosec B310
            return 0 if response.status == 200 else 1
    except OSError:
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    """Запускает процесс роли из настроек; `healthcheck` — проверка живости роли.

    Args:
        argv: Аргументы командной строки без имени программы (по умолчанию `sys.argv[1:]`).

    Returns:
        Код возврата процесса.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    role = settings.role
    if args == ["healthcheck"]:
        return healthcheck(role)
    if args and args[0] == "dlq":
        return run_dlq(args[1:])
    if args:
        print(
            f"Неизвестные аргументы: {args}. Использование: python -m app [healthcheck | dlq list|replay ...]",
            file=sys.stderr,
        )
        return 2

    logger_settings.setup_logging()
    app_logger.info("Запуск роли", role=str(role))
    match role:
        case AppRole.API | AppRole.ALL:
            run_api(role)
        case AppRole.WORKER:
            run_worker()
        case AppRole.MIGRATE:
            run_migrate()
        case AppRole.MEDIA_AGENT:
            app_logger.error("Роль media_agent появится на этапе 6 вместе с LiveKit (ADR-015).")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
