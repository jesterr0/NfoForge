from enum import Enum


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
