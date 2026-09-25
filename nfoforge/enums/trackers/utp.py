from enum import Enum


class UTPCategory(Enum):
    MOVIE = "1"
    TV = "2"


class UTPType(Enum):
    DISC = "1"
    REMUX = "2"
    ENCODE = "3"
    WEBDL = "4"
    WEBRIP = "5"
    HDTV = "6"


class UTPResolution(Enum):
    """UTP only ranks 1080i and above -- anything narrower correctly raises
    a TrackerError from Unit3dBaseUploader._get_resolution_id()."""

    RES_4320P = "1"
    RES_2160P = "2"
    RES_1080P = "3"
    RES_1080I = "4"
