from enum import auto as auto_enum
from typing_extensions import override
from src.enums import CaseInsensitiveEnum


class ScreenShotMode(CaseInsensitiveEnum):
    """
    BASIC_SS_GEN = Basic FFMPEG generated images
    SIMPLE_SS_COMP = FFMPEG generated comparison images
    ADV_SS_COMP = VapourSynth based generated comparison images (slower but with more features)
    """

    BASIC_SS_GEN = auto_enum()
    SIMPLE_SS_COMP = auto_enum()
    ADV_SS_COMP = auto_enum()

    @override
    def __str__(self) -> str:
        enum_map = {
            ScreenShotMode.BASIC_SS_GEN: "Basic Generation",
            ScreenShotMode.SIMPLE_SS_COMP: "Simple Comparison",
            ScreenShotMode.ADV_SS_COMP: "Advanced Comparison",
        }
        return enum_map[self]
