from enum import Enum


class LSTCategory(Enum):
    MOVIE = "1"
    TV = "2"
    MUSIC = "3"
    GAME = "4"
    APPLICATION = "5"
    XXX = "7"
    EBOOK = "8"
    EDUCATION = "9"
    FANRES = "10"


class LSTType(Enum):
    DISC = "1"
    REMUX = "2"
    ENCODE = "3"
    WEBDL = "4"
    WEBRIP = "5"
    HDTV = "6"
    OTHER = "15"


class LSTResolution(Enum):
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
