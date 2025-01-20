from enum import Enum, auto as auto_enum
from typing import Optional


class TrackerSelection(Enum):
    MORE_THAN_TV = auto_enum()
    TORRENT_LEECH = auto_enum()
    BEYOND_HD = auto_enum()
    PASS_THE_POPCORN = auto_enum()
    REELFLIX = auto_enum()
    AITHER = auto_enum()

    def __str__(self) -> str:
        str_map = {
            TrackerSelection.MORE_THAN_TV: "MoreThanTv",
            TrackerSelection.TORRENT_LEECH: "TorrentLeech",
            TrackerSelection.BEYOND_HD: "BeyondHD",
            TrackerSelection.PASS_THE_POPCORN: "PassThePopcorn",
            TrackerSelection.REELFLIX: "ReelFliX",
            TrackerSelection.AITHER: "Aither",
        }
        return str_map[self]

    @classmethod
    def _missing_(cls, value) -> Optional["TrackerSelection"]:
        """Override this method to attempt to locate the correct enum via case insensitive string"""
        value = str(value).lower()
        for member in cls:
            if str(member).lower() == value:
                return member
        return None
