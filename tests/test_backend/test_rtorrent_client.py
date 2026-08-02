from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
import xmlrpc.client

import pytest

from src.backend.torrent_clients.rtorrent import (
    RTorrentClient,
    _TimeoutSafeTransport,
    _TimeoutTransport,
)
from src.exceptions import TrackerClientError
from src.payloads.clients import RTorrentConfig


def _config(**kwargs: Any) -> RTorrentConfig:
    return RTorrentConfig(
        host="https://user:password@rtorrent.example/rpc",
        **kwargs,
    )


@patch("src.backend.torrent_clients.rtorrent.xmlrpc.client.Server")
def test_rtorrent_uses_verified_tls_and_socket_timeout(server: MagicMock) -> None:
    RTorrentClient(_config(), timeout=23)

    transport = server.call_args.kwargs["transport"]
    assert isinstance(transport, _TimeoutSafeTransport)
    assert transport.timeout == 23
    assert server.call_args.args[0] == "https://user:password@rtorrent.example/rpc"


@patch("src.backend.torrent_clients.rtorrent.xmlrpc.client.Server")
def test_rtorrent_can_explicitly_disable_tls_verification(server: MagicMock) -> None:
    with patch(
        "src.backend.torrent_clients.rtorrent.ssl._create_unverified_context"
    ) as create_context:
        RTorrentClient(_config(verify_tls=False), timeout=12)

    create_context.assert_called_once_with()
    assert isinstance(server.call_args.kwargs["transport"], _TimeoutSafeTransport)


@patch("src.backend.torrent_clients.rtorrent.xmlrpc.client.Server")
def test_rtorrent_http_transport_also_applies_timeout(server: MagicMock) -> None:
    RTorrentClient(RTorrentConfig(host="http://127.0.0.1/rpc"), timeout=9)

    transport = server.call_args.kwargs["transport"]
    assert isinstance(transport, _TimeoutTransport)
    assert transport.timeout == 9


def test_rtorrent_transports_set_connection_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_connection = SimpleNamespace()
    monkeypatch.setattr(
        xmlrpc.client.Transport,
        "make_connection",
        lambda _self, _host: http_connection,
    )
    transport = _TimeoutTransport(11)
    assert transport.make_connection("host") is http_connection
    assert http_connection.timeout == 11


def test_rtorrent_requires_a_host() -> None:
    with pytest.raises(TrackerClientError, match="Invalid host"):
        RTorrentClient(RTorrentConfig(host="  "))


@patch("src.backend.torrent_clients.rtorrent.xmlrpc.client.Server")
def test_rtorrent_confirm_fault_is_a_normal_missing_torrent(server: MagicMock) -> None:
    server.return_value.d.name.side_effect = xmlrpc.client.Fault(404, "not found")
    client = RTorrentClient(_config())

    assert client.confirm_injection("deadbeef") is False


@patch("src.backend.torrent_clients.rtorrent.xmlrpc.client.Server")
def test_rtorrent_injection_errors_are_wrapped_and_scrubbed(server: MagicMock) -> None:
    client = RTorrentClient(_config())
    client._get_torrent_obj = lambda _path: SimpleNamespace(infohash="deadbeef")  # type: ignore[method-assign]
    client._fast_resume = lambda torrent, _path: torrent  # type: ignore[method-assign]
    server.return_value.load.raw_start_verbose.side_effect = (
        xmlrpc.client.ProtocolError(
            "https://user:password@rtorrent.example/rpc", 500, "offline", {}
        )
    )

    with pytest.raises(TrackerClientError, match="Failed to inject") as error:
        client.inject_torrent(Path("release.torrent"), Path("release.mkv"))

    assert "password" not in str(error.value)
