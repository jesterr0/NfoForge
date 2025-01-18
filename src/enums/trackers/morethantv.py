from enum import Enum, auto as auto_enum
from src.enums import CaseInsensitiveEnum


class MTVCategories(Enum):
    DEFAULT = 0
    HD_MOVIES = 1
    SD_MOVIES = 2
    HD_EPISODE = 3
    SD_EPISODE = 4
    HD_SEASON = 5
    SD_SEASON = 6


class MTVAudioTags(Enum):
    AAC = "aac.audio"
    DD = "dd.audio"
    DDP = "ddp.audio"
    FLAC = "flac.audio"
    LPCM = "lpcm.audio"
    MP2 = "mp2.audio"
    MP3 = "mp3.audio"
    OPUS = "opus.audio"
    DTS = "dts.audio"
    DTS_HD = "dts.hd.audio"
    DTS_X = "dts.x.audio"
    TRUEHD = "truehd.audio"
    ATMOS = "atmos.audio"


class MTVResolutionIDs(Enum):
    DEFAULT = "0"
    RES_480 = "480"
    RES_720 = "720"
    RES_1080 = "1080"
    RES_1440 = "1440"
    RES_2160 = "2160"
    RES_4000 = "4000"
    RES_6000 = "6000"


class MTVSourceIDs(Enum):
    HDTV = auto_enum()
    SDTV = auto_enum()
    TV_RIP = auto_enum()
    DVD = auto_enum()
    DVD_RIP = auto_enum()
    VHS = auto_enum()
    BLURAY = auto_enum()
    BDRIP = auto_enum()
    WEBDL = auto_enum()
    WEBRIP = auto_enum()
    MIXED = auto_enum()
    UNKNOWN = auto_enum()


class MTVSourceOrigin(CaseInsensitiveEnum):
    UNDEFINED = auto_enum()
    INTERNAL = auto_enum()
    SCENE = auto_enum()
    P2P = auto_enum()
    USER = auto_enum()
    MIXED = auto_enum()
    OTHER = auto_enum()

    def __str__(self) -> str:
        str_map = {
            MTVSourceOrigin.UNDEFINED: "Undefined",
            MTVSourceOrigin.INTERNAL: "Internal",
            MTVSourceOrigin.SCENE: "Scene",
            MTVSourceOrigin.P2P: "P2P",
            MTVSourceOrigin.USER: "User",
            MTVSourceOrigin.MIXED: "Mixed",
            MTVSourceOrigin.OTHER: "Other",
        }
        return str_map[self]
