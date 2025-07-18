from enum import Enum, auto as auto_enum

from typing_extensions import override

from src.enums import CaseInsensitiveStrEnum


class TypeHierarchy(Enum):
    EXTRAS = auto_enum()
    CUT = auto_enum()
    LOCALIZATION = auto_enum()
    RE_RELEASE = auto_enum()

    @override
    def __str__(self) -> str:
        str_map = {
            TypeHierarchy.EXTRAS: "Extras",
            TypeHierarchy.CUT: "Cut",
            TypeHierarchy.LOCALIZATION: "Localization",
            TypeHierarchy.RE_RELEASE: "Re-Release",
        }
        return str_map[self]


class QualitySelection(CaseInsensitiveStrEnum):
    SDTV = "SDTV"
    HDTV = "HDTV"
    DVD = "DVD"
    WEB_RIP = "WEBRip"
    WEB_DL = "WEBDL"
    BLURAY = "BluRay"
