from enum import Enum


class UploadCXCategory(Enum):
    MOVIE = "1"
    TV = "2"


class UploadCXType(Enum):
    DISC = "1"
    REMUX = "2"
    WEBDL = "4"
    WEBRIP = "5"
    HDTV = "6"
    ENCODE = "3"


class UploadCXResolution(Enum):
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
