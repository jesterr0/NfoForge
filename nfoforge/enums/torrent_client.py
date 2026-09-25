from enum import auto as auto_enum
from typing import override

from nfoforge.enums import CaseInsensitiveEnum, CaseInsensitiveStrEnum


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


class QBittorrentAuthMode(CaseInsensitiveStrEnum):
    """Which credential NfoForge authenticates the qBittorrent Web API with.

    The two are alternatives, not a pair: an API key is sent as a bearer
    token on every request and makes the `auth/` endpoints answer 403, so a
    username and password alongside it would never be used.
    """

    USER_PASS = "Username & password"  # noqa: S105 - a mode label shown in the UI and stored in the profile, not a credential
    API_KEY = "API key"
