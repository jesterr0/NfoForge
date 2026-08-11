from collections.abc import Mapping
from types import MappingProxyType

from typing_extensions import override

from src.enums import CaseInsensitiveEnum


class TrackerSelection(CaseInsensitiveEnum):
    TORRENT_LEECH = "TorrentLeech"
    BEYOND_HD = "BeyondHD"
    PASS_THE_POPCORN = "PassThePopcorn"  # noqa: S105 - tracker name, not a credential
    REELFLIX = "ReelFliX"
    AITHER = "Aither"
    HUNO = "HUNO"
    LST = "LST"
    DARK_PEERS = "DarkPeers"
    SHARE_ISLAND = "ShareIsland"
    UPLOAD_CX = "UploadCX"
    ONLY_ENCODES = "OnlyEncodes"
    HDB = "HDBits"
    BLUTOPIA = "Blutopia"
    SEEDPOOL = "SeedPool"
    UTOPIA = "UTP"
    YU_SCENE = "Yu-scene"
    FEAR_NO_PEER = "FearNoPeer"

    @override
    def __str__(self) -> str:
        return self.value

    def get_root_url(self) -> str:
        """Return the root URL for each tracker."""
        return TRACKER_ROOT_URLS[self]


# immutable mapping from tracker selection to its root URL.
TRACKER_ROOT_URLS: Mapping[TrackerSelection, str] = MappingProxyType(
    {
        TrackerSelection.TORRENT_LEECH: "https://www.torrentleech.org/",
        TrackerSelection.BEYOND_HD: "https://beyond-hd.me/",
        TrackerSelection.PASS_THE_POPCORN: "https://passthepopcorn.me/",
        TrackerSelection.REELFLIX: "https://reelflix.cc/",
        TrackerSelection.AITHER: "https://aither.cc/",
        TrackerSelection.HUNO: "https://hawke.uno/",
        TrackerSelection.LST: "https://lst.gg/",
        TrackerSelection.DARK_PEERS: "https://darkpeers.org/",
        TrackerSelection.SHARE_ISLAND: "https://shareisland.org/",
        TrackerSelection.UPLOAD_CX: "https://upload.cx/",
        TrackerSelection.ONLY_ENCODES: "https://onlyencodes.cc/",
        TrackerSelection.HDB: "https://hdbits.org/",
        TrackerSelection.BLUTOPIA: "https://blutopia.cc/",
        TrackerSelection.SEEDPOOL: "https://seedpool.org/",
        TrackerSelection.UTOPIA: "https://utp.to/",
        TrackerSelection.YU_SCENE: "https://yu-scene.net/",
        TrackerSelection.FEAR_NO_PEER: "https://fearnopeer.com/",
    }
)
