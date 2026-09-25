from enum import Enum


class AitherCategory(Enum):
    MOVIE = "1"
    SPORT = "9"
    TV = "2"
    MUSIC = "3"


class AitherType(Enum):
    DISC = "1"
    REMUX = "2"
    ENCODE = "3"
    WEBDL = "4"
    WEBRIP = "5"
    HDTV = "6"
    OTHER = "7"


class AitherResolution(Enum):
    RES_4320P = "1"
    RES_2160P = "2"
    RES_1080P = "3"
    RES_1080I = "4"
    RES_720P = "5"
    RES_576P = "6"
    RES_576I = "7"
    RES_480P = "8"
    RES_480I = "9"
    RES_OTHER = "10"
