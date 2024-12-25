from enum import auto as auto_enum
from src.enums import CaseInsensitiveEnum


class TorrentClientSelection(CaseInsensitiveEnum):
    QBITTORRENT = auto_enum()
    DELUGE = auto_enum()
    RTORRENT = auto_enum()
    TRANSMISSION = auto_enum()
    WATCH_FOLDER = auto_enum()

    def __str__(self):
        str_map = {
            TorrentClientSelection.QBITTORRENT: "QBittorrent",
            TorrentClientSelection.DELUGE: "Deluge",
            TorrentClientSelection.RTORRENT: "rTorrent",
            TorrentClientSelection.TRANSMISSION: "Transmission",
            TorrentClientSelection.WATCH_FOLDER: "Watch Folder",
        }
        return str_map[self]
