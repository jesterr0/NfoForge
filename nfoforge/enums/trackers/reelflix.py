from enum import Enum


class ReelFlixCategory(Enum):
    MOVIE = "1"


class ReelFlixType(Enum):
    DISC = "43"
    REMUX = "40"
    WEBDL = "42"
    WEBRIP = "45"
    ENCODE = "41"
    HDTV = "35"


class ReelFlixResolution(Enum):
    RES_4320P = "1"
    RES_2160P = "2"
    RES_1080P = "3"
    RES_1080I = "4"
    RES_720P = "5"
    RES_576P = "6"
    RES_576I = "7"
    RES_480P = "8"
    RES_480I = "9"
