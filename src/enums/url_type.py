from enum import auto as auto_enum
from src.enums import CaseInsensitiveEnum


class URLType(CaseInsensitiveEnum):
    BBCODE = auto_enum()
    HTML = auto_enum()

    def __str__(self) -> str:
        if self == URLType.HTML:
            return "HTML"
        elif self == URLType.BBCODE:
            return "BBCode"
