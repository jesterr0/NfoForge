from src.enums import CaseInsensitiveEnum
from typing_extensions import override


class SubtitleAlignment(CaseInsensitiveEnum):
    BOTTOM_LEFT = 1
    BOTTOM_CENTER = 2
    BOTTOM_RIGHT = 3
    CENTER_LEFT = 4
    CENTER_CENTER = 5
    CENTER_RIGHT = 6
    TOP_LEFT = 7
    TOP_CENTER = 8
    TOP_RIGHT = 9

    @override
    def __str__(self) -> str:
        mapping = {
            SubtitleAlignment.BOTTOM_LEFT: "Bottom Left",
            SubtitleAlignment.BOTTOM_CENTER: "Bottom Center",
            SubtitleAlignment.BOTTOM_RIGHT: "Bottom Right",
            SubtitleAlignment.CENTER_LEFT: "Center Left",
            SubtitleAlignment.CENTER_CENTER: "Center",
            SubtitleAlignment.CENTER_RIGHT: "Center Right",
            SubtitleAlignment.TOP_LEFT: "Top Left",
            SubtitleAlignment.TOP_CENTER: "Top Center",
            SubtitleAlignment.TOP_RIGHT: "Top Right",
        }
        return mapping[self]
