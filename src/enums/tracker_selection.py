from typing_extensions import override

from src.enums import CaseInsensitiveEnum


class TrackerSelection(CaseInsensitiveEnum):
    MORE_THAN_TV = "MoreThanTV"
    TORRENT_LEECH = "TorrentLeech"
    BEYOND_HD = "BeyondHD"
    PASS_THE_POPCORN = "PassThePopcorn"
    REELFLIX = "ReelFliX"
    AITHER = "Aither"
    HUNO = "HUNO"
    LST = "LST"
    DARK_PEERS = "DarkPeers"
    SHARE_ISLAND = "ShareIsland"

    @override
    def __str__(self) -> str:
        return self.value
