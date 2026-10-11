"""Минимальный SMTP-сервер на 127.0.0.1 для интеграционных тестов `SmtpMailClient` (SYS-10-R21).

Тесты не ходят во внешнюю сеть и не зависят от Mailpit: сервер в процессе теста принимает
EHLO/HELO, MAIL, RCPT, DATA, RSET, NOOP, QUIT и сохраняет конверт и сырое письмо.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass
class ReceivedMail:
    """Письмо, принятое тестовым сервером."""

    sender: str
    recipients: list[str]
    data: bytes


@dataclass
class SmtpTestServer:
    """Адрес запущенного сервера и принятые письма."""

    host: str
    port: int
    received: list[ReceivedMail] = field(default_factory=list)


def _address(argument: str) -> str:
    """Адрес из `MAIL FROM:<a@b>` / `RCPT TO:<a@b>`."""
    return argument.split(":", 1)[1].strip().split(" ", 1)[0].strip("<>")


@asynccontextmanager
async def smtp_test_server() -> AsyncIterator[SmtpTestServer]:
    """Запускает сервер на свободном порту 127.0.0.1 на время блока."""
    state = SmtpTestServer(host="127.0.0.1", port=0)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        sender, recipients = "", list[str]()
        writer.write(b"220 localhost ESMTP test\r\n")
        while line := await reader.readline():
            command = line.decode().rstrip("\r\n")
            verb = command.split(" ", 1)[0].upper()
            if verb in ("EHLO", "HELO"):
                writer.write(b"250-localhost\r\n250 8BITMIME\r\n")
            elif verb == "MAIL":
                sender, recipients = _address(command), []
                writer.write(b"250 OK\r\n")
            elif verb == "RCPT":
                recipients.append(_address(command))
                writer.write(b"250 OK\r\n")
            elif verb == "DATA":
                writer.write(b"354 End data with <CR><LF>.<CR><LF>\r\n")
                await writer.drain()
                data = await reader.readuntil(b"\r\n.\r\n")
                state.received.append(ReceivedMail(sender, recipients, data[: -len(b"\r\n.\r\n")]))
                writer.write(b"250 OK queued\r\n")
            elif verb in ("RSET", "NOOP"):
                writer.write(b"250 OK\r\n")
            elif verb == "QUIT":
                writer.write(b"221 Bye\r\n")
                await writer.drain()
                break
            else:
                writer.write(b"502 Command not implemented\r\n")
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, state.host, 0)
    state.port = server.sockets[0].getsockname()[1]
    try:
        yield state
    finally:
        server.close()
        await server.wait_closed()
