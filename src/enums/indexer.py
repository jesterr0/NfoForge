from enum import auto as auto_enum
from src.enums import CaseInsensitiveEnum


class Indexer(CaseInsensitiveEnum):
    LSMASH = auto_enum()
    FFMS2 = auto_enum()

    def __str__(self) -> str:
        if self == Indexer.LSMASH:
            return "lsmash"
        elif self == Indexer.FFMS2:
            return "ffms2"
