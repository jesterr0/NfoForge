from enum import Enum


class ShareIslandCategory(Enum):
    MOVIE = "1"
    TV = "2"


class ShareIslandType(Enum):
    DISC = "26"
    REMUX = "7"
    WEBDL = "27"
    WEBRIP = "15"
    HDTV = "6"
    ENCODE = "15"


class ShareIslandResolution(Enum):
    RES_8640p = "10"
    RES_4320P = "1"
    RES_2160P = "2"
    RES_1080P = "3"
    RES_1080I = "4"
    RES_720P = "5"
    RES_576P = "6"
    RES_576I = "7"
    RES_480P = "8"
    RES_480I = "9"
