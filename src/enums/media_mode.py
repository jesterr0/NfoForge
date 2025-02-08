from enum import auto as auto_enum
from typing_extensions import override
from src.enums import CaseInsensitiveEnum


class MediaMode(CaseInsensitiveEnum):
    MOVIES = auto_enum()
    SERIES = auto_enum()

    @override
    def __str__(self):
        str_map = {MediaMode.MOVIES: "Movies", MediaMode.SERIES: "Series"}
        return str_map[self]
