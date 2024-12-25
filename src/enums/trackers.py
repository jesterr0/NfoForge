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
        if self == MTVSourceOrigin.UNDEFINED:
            return "Undefined"
        elif self == MTVSourceOrigin.INTERNAL:
            return "Internal"
        elif self == MTVSourceOrigin.SCENE:
            return "Scene"
        elif self == MTVSourceOrigin.P2P:
            return "P2P"
        elif self == MTVSourceOrigin.USER:
            return "User"
        elif self == MTVSourceOrigin.MIXED:
            return "Mixed"
        elif self == MTVSourceOrigin.OTHER:
            return "Other"


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
        if self == BHDPromo.NO_PROMO:
            return "No Promo"
        elif self == BHDPromo.PROMO_25:
            return "25% Promo"
        elif self == BHDPromo.PROMO_50:
            return "50% Promo"
        elif self == BHDPromo.PROMO_75:
            return "75% Promo"
        elif self == BHDPromo.FREELEECH:
            return "Freeleech"
        elif self == BHDPromo.FREELEECH_LIMITED_UL:
            return "Freeleech (Limited UL)"


class BHDLiveRelease(Enum):
    DRAFT = 0
    LIVE = 1

    def __str__(self) -> str:
        if self == BHDLiveRelease.DRAFT:
            return "Draft"
        elif self == BHDLiveRelease.LIVE:
            return "Live"
