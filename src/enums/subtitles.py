from src.enums import CaseInsensitiveEnum


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

    def __str__(self) -> str:
        if self == SubtitleAlignment.BOTTOM_LEFT:
            return "Bottom Left"
        elif self == SubtitleAlignment.BOTTOM_CENTER:
            return "Bottom Center"
        elif self == SubtitleAlignment.BOTTOM_RIGHT:
            return "Bottom Right"
        elif self == SubtitleAlignment.CENTER_LEFT:
            return "Center Left"
        elif self == SubtitleAlignment.CENTER_CENTER:
            return "Center"
        elif self == SubtitleAlignment.CENTER_RIGHT:
            return "Center Right"
        elif self == SubtitleAlignment.TOP_LEFT:
            return "Top Left"
        elif self == SubtitleAlignment.TOP_CENTER:
            return "Top Center"
        elif self == SubtitleAlignment.TOP_RIGHT:
            return "Top Right"
