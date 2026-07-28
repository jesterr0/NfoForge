from pathlib import Path
from unittest.mock import MagicMock, patch

from src.backend.torrent_clients.qbittorrent import QBittorrentClient
from src.payloads.clients import TorrentClient


def _config() -> TorrentClient:
    return TorrentClient(
        host="http://127.0.0.1",
        port=8080,
        user="user",
        password="password",
        specific_params={
            "category": "Movies",
            "super_seeding": False,
            "save_path_mode": "Client default",
            "save_path_template": "",
        },
    )


@patch("src.backend.torrent_clients.qbittorrent.QBitClient")
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


@patch("src.backend.torrent_clients.qbittorrent.QBitClient")
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
        is_skip_checking=True,
        category="Movies",
    )


@patch("src.backend.torrent_clients.qbittorrent.QBitClient")
def test_blank_save_path_keeps_automatic_management(qbit_api: MagicMock) -> None:
    api = qbit_api.return_value
    api.torrents_add.return_value = "Ok."
    client = QBittorrentClient(_config())

    assert client.inject_torrent(Path("release.torrent"), "   ")[0] is True

    assert api.torrents_add.call_args.kwargs["save_path"] is None
    assert api.torrents_add.call_args.kwargs["use_auto_torrent_management"] is True
