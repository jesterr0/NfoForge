from enum import Enum


class HunoCategory(Enum):
    MOVIE = "1"
    TV = "2"


class HunoType(Enum):
    REMUX = "2"
    WEBDL = "3"
    WEBRIP = "3"
    ENCODE = "15"
    DISC = "1"


class HunoResolution(Enum):
    RES_4320P = "1"
    RES_2160P = "2"
    RES_1080P = "3"
    RES_1080I = "4"
    RES_720P = "5"
    RES_576P = "6"
    RES_576I = "7"
    RES_540P = "11"
    RES_480P = "8"
    RES_480I = "9"
    RES_OTHER = "10"
