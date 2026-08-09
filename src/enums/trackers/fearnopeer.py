from enum import Enum


class FearNoPeerCategory(Enum):
    MOVIE = "1"
    TV = "2"


class FearNoPeerType(Enum):
    DISC = "1"
    REMUX = "2"
    ENCODE = "3"
    WEBDL = "4"
    WEBRIP = "5"
    HDTV = "6"


class FearNoPeerResolution(Enum):
    RES_4320P = "1"
    RES_2160P = "2"
    RES_1080P = "3"
    RES_1080I = "11"
    RES_720P = "5"
    RES_576P = "6"
    RES_576I = "15"
    RES_480P = "8"
    RES_480I = "14"
