from enum import Enum, auto as auto_enum
from src.enums import CaseInsensitiveEnum


# TorrentLeech
class TLCategories(Enum):
    ANIME = 34
    MOVIE_4K = 47
    MOVIE_BLURAY = 13
    MOVIE_BLURAY_RIP = 14
    MOVIE_CAM = 8
    MOVIE_TS = 9
    MOVIE_DOCUMENTARY = 29
    MOVIE_DVD = 12
    MOVIE_DVD_RIP = 11
    MOVIE_FOREIGN = 36
    MOVIE_HD_RIP = 43
    MOVIE_WEB_RIP = 37
    TV_BOX_SETS = 27
    TV_EPISODES = 26
    TV_EPISODES_HD = 32
    TV_FOREIGN = 44


# MoreThanTv
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


# BeyondHD
class BHDCategoryID(Enum):
    MOVIE = 1
    TV = 2


class BHDType(Enum):
    BD_25 = "BD 25"
    BD_50 = "BD 50"
    BD_REMUX = "BD Remux"
    DVD_5 = "DVD 5"
    DVD_9 = "DVD 9"
    DVD_REMUX = "DVD Remux"
    P_1080I = "1080i"
    P_1080P = "1080p"
    P_2160P = "2160p"
    P_480P = "480p"
    P_540P = "540p"
    P_576P = "576p"
    P_720P = "720p"
    UHD_100 = "UHD 100"
    UHD_50 = "UHD 50"
    UHD_66 = "UHD 66"
    UHD_REMUX = "UHD Remux"
    OTHER = "Other"


class BHDSource(Enum):
    BLURAY = "Blu-ray"
    DVD = "DVD"
    HD_DVD = "HD-DVD"
    HDTV = "HDTV"
    WEB = "WEB"


class BHDPromo(Enum):
    NO_PROMO = 0
    PROMO_25 = 1
    PROMO_50 = 2
    PROMO_75 = 3
    FREELEECH = 4
    FREELEECH_LIMITED_UL = 5

    def __str__(self) -> str:
        str_map = {
            BHDPromo.NO_PROMO: "No Promo",
            BHDPromo.PROMO_25: "25% Promo",
            BHDPromo.PROMO_50: "50% Promo",
            BHDPromo.PROMO_75: "75% Promo",
            BHDPromo.FREELEECH: "Freeleech",
            BHDPromo.FREELEECH_LIMITED_UL: "Freeleech (Limited UL)",
        }
        return str_map[self]


class BHDLiveRelease(Enum):
    DRAFT = 0
    LIVE = 1

    def __str__(self) -> str:
        str_map = {
            BHDLiveRelease.DRAFT: "Draft",
            BHDLiveRelease.LIVE: "Live",
        }
        return str_map[self]


class PTPResolution(Enum):
    # PAL = "PAL" # TODO: implement
    RES_480P = "480p"
    RES_576P = "576p"
    RES_720P = "720p"
    RES_1080I = "1080i"
    RES_1080P = "1080p"
    RES_2160P = "2160p"
    OTHER = "Other"


class PTPType(Enum):
    FEATURE_FILM = "Feature Film"
    SHORT_FILM = "Short Film"
    MINI_SERIES = "Miniseries"
    STAND_UP_COMEDY = "Stand-up Comedy"
    LIVE_PERFORMANCE = "Live Performance"
    MOVIE_COLLECTION = "Movie Collection"


class PTPCodec(Enum):
    AUTO_DETECT = "* Auto-detect"
    XVID = "XviD"
    DIVX = "DivX"
    H264 = "H.264"
    X264 = "x264"
    H265 = "H.265"
    X265 = "x265"
    DVD5 = "DVD5"
    DVD9 = "DVD9"
    BD25 = "BD25"
    BD50 = "BD50"
    BD66 = "BD66"
    BD100 = "BD100"
    OTHER = "Other"


class PTPContainer(Enum):
    AUTO_DETECT = "* Auto-detect"
    AVI = "AVI"
    MPG = "MPG"
    MKV = "MKV"
    MP4 = "MP4"
    VOB_IFO = "VOB IFO"
    ISO = "ISO"
    M2TS = "m2ts"
    OTHER = "Other"


class PTPSource(Enum):
    BLU_RAY = "Blu-ray"
    DVD = "DVD"
    WEB = "WEB"
    NONE = "---"
    HD_DVD = "HD-DVD"
    HDTV = "HDTV"
    TV = "TV"
    VHS = "VHS"
    OTHER = "Other"
