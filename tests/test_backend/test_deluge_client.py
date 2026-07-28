from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from deluge_web_client import TorrentOptions
from deluge_web_client.schema import Response
import pytest

from src.backend.torrent_clients.deluge import DelugeClient
from src.exceptions import TrackerClientError
from src.payloads.clients import DelugeConfig


def deluge_config(**kwargs: Any) -> DelugeConfig:
    return DelugeConfig(
        host="https://deluge.example.test",
        password="secret",
        **kwargs,
    )


@pytest.mark.parametrize("config", [DelugeConfig(), DelugeConfig(host="host")])
def test_deluge_client_requires_host_and_password(config: DelugeConfig) -> None:
    with pytest.raises(TrackerClientError, match="Host and password"):
        DelugeClient(config)


@patch("src.backend.torrent_clients.deluge.DelugeWebClient")
def test_deluge_client_login_uses_configured_timeout(
    client_class: MagicMock,
) -> None:
    client_class.return_value.login.return_value = Response(result=True)
    client = DelugeClient(deluge_config(), timeout=42)

    assert client.login() == (True, "Login successful")
    client_class.return_value.login.assert_called_once_with(timeout=42)


@patch("src.backend.torrent_clients.deluge.DelugeWebClient")
def test_deluge_client_login_reports_response_failure(
    client_class: MagicMock,
) -> None:
    client_class.return_value.login.return_value = Response(
        result=False, error="invalid password"
    )
    client = DelugeClient(deluge_config())

    with pytest.raises(TrackerClientError, match="invalid password"):
        client.login()


@patch("src.backend.torrent_clients.deluge.DelugeWebClient")
def test_deluge_client_test_reports_success(client_class: MagicMock) -> None:
    client_class.return_value.login.return_value = Response(result=True)

    assert DelugeClient(deluge_config()).test()[0] is True


@patch("src.backend.torrent_clients.deluge.DelugeWebClient")
def test_deluge_client_uploads_with_v2_torrent_options(
    client_class: MagicMock, tmp_path: Path
) -> None:
    torrent_path = tmp_path / "release.torrent"
    torrent_path.touch()
    client_class.return_value.upload_torrent.return_value = Response(
        result="info-hash", message="Torrent added successfully"
    )
    client = DelugeClient(
        deluge_config(path=" /downloads ", label=" TV "),
        timeout=42,
    )

    assert client.inject_torrent(torrent_path) == (
        True,
        "Torrent added successfully",
    )
    client_class.return_value.upload_torrent.assert_called_once_with(
        torrent_path=torrent_path,
        torrent_options=TorrentOptions(
            seed_mode=True,
            auto_managed=True,
            download_location="/downloads",
            label="TV",
        ),
        timeout=42,
    )


def test_deluge_client_omits_blank_label_and_save_directory() -> None:
    client = DelugeClient(deluge_config(path="  ", label="  "))

    assert client._get_save_directory() is None
    assert client._get_label() is None


@patch("src.backend.torrent_clients.deluge.DelugeWebClient")
def test_deluge_client_reports_unsuccessful_upload(client_class: MagicMock) -> None:
    client_class.return_value.upload_torrent.return_value = Response(
        result=None, error="permission denied"
    )
    client = DelugeClient(deluge_config())

    assert client.inject_torrent(Path("release.torrent")) == (
        False,
        "Deluge injection failed: permission denied",
    )


@patch("src.backend.torrent_clients.deluge.DelugeWebClient")
def test_deluge_client_wraps_upload_errors(client_class: MagicMock) -> None:
    client_class.return_value.upload_torrent.side_effect = RuntimeError("offline")
    client = DelugeClient(deluge_config())

    with pytest.raises(TrackerClientError, match="offline"):
        client.inject_torrent(Path("release.torrent"))


@patch("src.backend.torrent_clients.deluge.DelugeWebClient")
def test_deluge_client_logout_only_closes_local_session(
    client_class: MagicMock,
) -> None:
    client = DelugeClient(deluge_config())

    client.logout()

    client_class.return_value.close_session.assert_called_once_with()
    client_class.return_value.disconnect.assert_not_called()
