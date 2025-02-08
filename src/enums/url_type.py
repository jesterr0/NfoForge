from enum import auto as auto_enum
from typing_extensions import override
from src.enums import CaseInsensitiveEnum


class URLType(CaseInsensitiveEnum):
    BBCODE = auto_enum()
    HTML = auto_enum()

    @override
    def __str__(self) -> str:
        str_map = {
            URLType.HTML: "HTML",
            URLType.BBCODE: "BBCode",
        }
        return str_map[self]
