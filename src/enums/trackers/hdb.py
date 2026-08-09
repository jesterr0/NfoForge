from enum import Enum


class HDBCategory(Enum):
    MOVIE = 1
    TV = 2
    DOCUMENTARY = 3


class HDBCodec(Enum):
    AVC = 1
    MPEG2 = 2
    VC1 = 3
    XVID = 4
    HEVC = 5
    VP9 = 6


class HDBMedium(Enum):
    BLURAY = 1
    ENCODE = 3
    CAPTURE = 4
    REMUX = 5
    WEBDL = 6
