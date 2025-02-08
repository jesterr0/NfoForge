from enum import auto as auto_enum
from typing_extensions import override
from src.enums import CaseInsensitiveEnum


class Indexer(CaseInsensitiveEnum):
    LSMASH = auto_enum()
    FFMS2 = auto_enum()

    @override
    def __str__(self) -> str:
        str_map = {Indexer.LSMASH: "lsmash", Indexer.FFMS2: "ffms2"}
        return str_map[self]
