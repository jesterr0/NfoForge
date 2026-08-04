from enum import auto as auto_enum

from typing_extensions import override

from src.enums import CaseInsensitiveEnum, CaseInsensitiveStrEnum


class TorrentClientSelection(CaseInsensitiveEnum):
    QBITTORRENT = auto_enum()
    DELUGE = auto_enum()
    RTORRENT = auto_enum()
    TRANSMISSION = auto_enum()
    WATCH_FOLDER = auto_enum()

    @override
    def __str__(self) -> str:
        str_map = {
            TorrentClientSelection.QBITTORRENT: "QBittorrent",
            TorrentClientSelection.DELUGE: "Deluge",
            TorrentClientSelection.RTORRENT: "rTorrent",
            TorrentClientSelection.TRANSMISSION: "Transmission",
            TorrentClientSelection.WATCH_FOLDER: "Watch Folder",
        }
        return str_map[self]


class QBittorrentSavePathMode(CaseInsensitiveStrEnum):
    """How NfoForge chooses qBittorrent's save path for injected torrents."""

    CLIENT_DEFAULT = "Client default"
    SOURCE = "Source location"
    TEMPLATE = "Template"
