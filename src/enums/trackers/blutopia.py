from enum import Enum


class BlutopiaCategory(Enum):
    MOVIE = "1"
    TV = "2"


class BlutopiaType(Enum):
    DISC = "1"
    REMUX = "3"
    WEBDL = "4"
    WEBRIP = "5"
    HDTV = "6"
    ENCODE = "12"


class BlutopiaResolution(Enum):
    RES_8640P = "10"
    RES_4320P = "11"
    RES_2160P = "1"
    RES_1080P = "2"
    RES_1080I = "3"
    RES_720P = "5"
    RES_576P = "6"
    RES_576I = "7"
    RES_480P = "8"
    RES_480I = "9"
