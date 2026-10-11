"""Управление стендом N3 из тестов: docker compose, состояние серверов HAProxy (SYS-05-R46).

Стенд поднимает `make stand-up` (docker-compose.yml + docker-compose.ci.yml, проект `flt`).
Контейнеры называются `<project>-<service>-<n>` (SYS-11-R28): `flt-api-2`, `flt-worker-1`.
Состояние серверов HAProxy читается со страницы `stats;csv` на внутреннем порту 8404 изнутри
контейнера `haproxy` (порт наружу не публикуется — ADR-012).
"""

import asyncio
import csv
import io
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from tests.support.eventually import eventually


INSTANCE_HEADER = "X-Instance-Id"
DEFAULT_PROJECT = "flt"
API_SERVICE = "api"
API_PORT = 8000
API_BACKEND = "be_api"
HAPROXY_STATS_URL = "http://127.0.0.1:8404/stats;csv"
# Опрос состояния внешних процессов — шаг 0,5 с (исключение SYS-10-R17 для tests/n_instances).
POLL_INTERVAL_SECONDS = 0.5
HTTP_TIMEOUT_SECONDS = 10.0


# Фабрика клиента прямого доступа к n-му инстансу и действие над контейнером (фикстуры conftest).
type OnInstance = Callable[[int], httpx.AsyncClient]
type ContainerAction = Callable[[str], Awaitable[str]]


class StandCommandError(RuntimeError):
    """Команда docker завершилась с ошибкой."""


@dataclass(frozen=True)
class Instance:
    """Инстанс роли api на стенде.

    Attributes:
        index: Номер реплики compose (1…N).
        container: Имя контейнера (`flt-api-2`).
        instance_id: Значение `X-Instance-Id` (HOSTNAME контейнера).
        url: Прямой адрес инстанса с хоста, мимо HAProxy.
    """

    index: int
    container: str
    instance_id: str
    url: str


@dataclass(frozen=True)
class ServerState:
    """Строка сервера backend-а на странице статистики HAProxy."""

    name: str
    address: str
    status: str

    @property
    def ip(self) -> str:
        """IP-адрес сервера без порта (пусто для незанятого слота server-template)."""
        return self.address.rpartition(":")[0]


class Stand:
    """Стенд N3: HAProxy по `url`, контейнеры проекта compose `project`."""

    def __init__(self, url: str, project: str = DEFAULT_PROJECT) -> None:
        """Создаёт описание стенда.

        Args:
            url: Адрес HAProxy (`--stand-url`).
            project: Имя проекта docker compose (`--stand-project`, по умолчанию `flt`).
        """
        self.url = url.rstrip("/")
        self.project = project

    def container(self, name: str) -> str:
        """Имя контейнера в проекте стенда: `flt-api-2` → `<project>-api-2`, `api-2` → `<project>-api-2`."""
        default_prefix = f"{DEFAULT_PROJECT}-"
        if name.startswith(default_prefix):
            name = name.removeprefix(default_prefix)
        return f"{self.project}-{name}"

    async def docker(self, *args: str) -> str:
        """Выполняет `docker <args>` и возвращает stdout.

        Raises:
            StandCommandError: Ненулевой код возврата.
        """
        process = await asyncio.create_subprocess_exec(
            "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise StandCommandError(f"docker {' '.join(args)}: {stderr.decode().strip()}")
        return stdout.decode()

    async def compose(self, *args: str) -> str:
        """Выполняет `docker compose -p <project> <args>`."""
        return await self.docker("compose", "-p", self.project, *args)

    async def instances(self) -> list[Instance]:
        """Работающие инстансы роли api, упорядоченные по номеру реплики.

        Адрес — опубликованный порт из диапазона 8000-8009 (`docker compose port --index`),
        идентификатор — заголовок `X-Instance-Id` ответа `GET /v1/health` инстанса.
        """
        names = (await self.compose("ps", "--format", "{{.Name}}", API_SERVICE)).split()
        prefix = f"{self.project}-{API_SERVICE}-"
        indices = sorted(int(name.removeprefix(prefix)) for name in names if name.startswith(prefix))
        result: list[Instance] = []
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            for index in indices:
                address = (await self.compose("port", "--index", str(index), API_SERVICE, str(API_PORT))).strip()
                url = f"http://{address}"
                response = await client.get(f"{url}/v1/health")
                result.append(Instance(index, f"{prefix}{index}", response.headers[INSTANCE_HEADER], url))
        return result

    async def haproxy_servers(self, backend: str = API_BACKEND) -> list[ServerState]:
        """Серверы backend-а HAProxy со страницы `stats;csv` (без строки BACKEND)."""
        raw = await self.compose("exec", "-T", "haproxy", "wget", "-qO-", HAPROXY_STATS_URL)
        reader = csv.DictReader(io.StringIO(raw.removeprefix("# ")))
        return [
            ServerState(name=row["svname"], address=row.get("addr") or "", status=row["status"])
            for row in reader
            if row["pxname"] == backend and row["svname"] not in ("FRONTEND", "BACKEND")
        ]

    async def container_ip(self, container: str) -> str:
        """IP контейнера в сети compose (пусто у остановленного контейнера)."""
        output = await self.docker(
            "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container
        )
        return output.strip()

    async def server_status(self, ip: str, backend: str = API_BACKEND) -> str | None:
        """Статус сервера HAProxy с адресом `ip` или None, если такого сервера нет."""
        for server in await self.haproxy_servers(backend):
            if server.ip == ip:
                return server.status
        return None

    async def up_servers(self, backend: str = API_BACKEND) -> list[ServerState]:
        """Серверы backend-а в состоянии UP."""
        return [server for server in await self.haproxy_servers(backend) if server.status == "UP"]

    async def wait_server_down(self, ip: str, within: float) -> None:
        """Ждёт, пока HAProxy исключит сервер `ip` из балансировки (DOWN, MAINT или удалён из DNS)."""

        async def excluded() -> bool:
            status = await self.server_status(ip)
            return status is None or status.startswith(("DOWN", "MAINT"))

        await eventually(excluded, timeout=within, interval=POLL_INTERVAL_SECONDS)

    async def wait_container_up(self, container: str, within: float) -> None:
        """Ждёт, пока сервер контейнера `container` снова в состоянии UP в HAProxy."""

        async def is_up() -> bool:
            ip = await self.container_ip(container)
            return bool(ip) and await self.server_status(ip) == "UP"

        await eventually(is_up, timeout=within, interval=POLL_INTERVAL_SECONDS)
