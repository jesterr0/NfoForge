from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.backend.torrent_clients.qbittorrent import QBittorrentClient
from src.backend.torrent_clients.qbittorrent.save_path import (
    get_qbittorrent_save_path_warning,
)
from src.enums.torrent_client import QBittorrentSavePathMode
from src.exceptions import TrackerClientError
from src.payloads.clients import QBittorrentConfig


def _config() -> QBittorrentConfig:
    return QBittorrentConfig(
        host="http://127.0.0.1",
        port=8080,
        user="user",
        password="password",
        category="Movies",
        super_seeding=False,
        save_path_mode=QBittorrentSavePathMode.CLIENT_DEFAULT,
    )


@patch("src.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_inject_without_save_path_keeps_automatic_management(
    qbit_api: MagicMock,
) -> None:
    api = qbit_api.return_value
    api.torrents_add.return_value = "Ok."
    client = QBittorrentClient(_config())

    assert client.inject_torrent(Path("release.torrent")) == (
        True,
        "qBittorrent injection successful",
    )

    api.torrents_add.assert_called_once_with(
        torrent_files="release.torrent",
        save_path=None,
        use_auto_torrent_management=True,
        is_skip_checking=True,
        category="Movies",
    )


@patch("src.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_inject_with_save_path_uses_manual_management_and_preserves_path(
    qbit_api: MagicMock,
) -> None:
    api = qbit_api.return_value
    api.torrents_add.return_value = "Ok."
    client = QBittorrentClient(_config())
    save_path = r"\\plex_server\movies\Cleaner (2025)"

    assert client.inject_torrent(Path("release.torrent"), save_path) == (
        True,
        "qBittorrent injection successful",
    )

    api.torrents_add.assert_called_once_with(
        torrent_files="release.torrent",
        save_path=save_path,
        use_auto_torrent_management=False,
        is_skip_checking=False,
        category="Movies",
    )


@patch("src.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_blank_save_path_keeps_automatic_management(qbit_api: MagicMock) -> None:
    api = qbit_api.return_value
    api.torrents_add.return_value = "Ok."
    client = QBittorrentClient(_config())

    assert client.inject_torrent(Path("release.torrent"), "   ")[0] is True

    assert api.torrents_add.call_args.kwargs["save_path"] is None
    assert api.torrents_add.call_args.kwargs["use_auto_torrent_management"] is True


@patch("src.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_qbittorrent_rejects_blank_host(qbit_api: MagicMock) -> None:
    config = _config()
    config.host = "  "

    with pytest.raises(TrackerClientError, match="Hostname must be defined"):
        QBittorrentClient(config)

    qbit_api.assert_not_called()


def test_remote_qbittorrent_warns_for_windows_drive_path() -> None:
    warning = get_qbittorrent_save_path_warning(
        "https://seedbox.example",
        r"C:\Media\Movies",
    )

    assert warning is not None
    assert "remote" in warning


def test_local_qbittorrent_allows_windows_drive_path() -> None:
    assert (
        get_qbittorrent_save_path_warning(
            "http://127.0.0.1:8080",
            r"C:\Media\Movies",
        )
        is None
    )
