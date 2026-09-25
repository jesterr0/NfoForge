from enum import Enum


class OnlyEncodesCategory(Enum):
    MOVIE = "1"
    TV = "2"


class OnlyEncodesType(Enum):
    DISC = "19"
    REMUX = "20"
    WEBDL = "21"
    ENCODE_X265 = "10"
    ENCODE_AV1 = "14"
    ENCODE_X264 = "15"


class OnlyEncodesResolution(Enum):
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
