from enum import auto as auto_enum
from src.enums import CaseInsensitiveEnum


class MediaMode(CaseInsensitiveEnum):
    MOVIES = auto_enum()
    SERIES = auto_enum()

    def __str__(self):
        if self == MediaMode.MOVIES:
            return "Movies"
        elif self == MediaMode.SERIES:
            return "Series"
