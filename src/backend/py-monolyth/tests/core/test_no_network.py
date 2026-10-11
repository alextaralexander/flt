"""Тесты детерминизма окружения pytest: без внешней сети (SYS-10-R37)."""

import socket

import pytest
from pytest_socket import SocketBlockedError, SocketConnectBlockedError


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-10-R37")]


@pytest.mark.filterwarnings("ignore:A test tried to use socket:UserWarning")
def test_external_socket_blocked() -> None:
    """Соединение с внешним адресом запрещено pytest-socket (`--disable-socket --allow-hosts`)."""
    # - Act / Assert -
    with pytest.raises((SocketBlockedError, SocketConnectBlockedError)):
        socket.create_connection(("192.0.2.1", 443), timeout=1)


def test_loopback_is_allowed() -> None:
    """Loopback разрешён: интеграционные тесты ходят в локальные PostgreSQL и Redis."""
    # - Arrange -
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)

        # - Act -
        with socket.create_connection(server.getsockname(), timeout=1) as client:
            # - Assert -
            assert client.getpeername() == server.getsockname()
