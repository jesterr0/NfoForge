from enum import auto as auto_enum
from src.enums import CaseInsensitiveEnum


class ColonReplace(CaseInsensitiveEnum):
    KEEP = auto_enum()
    DELETE = auto_enum()
    REPLACE_WITH_DASH = auto_enum()
    REPLACE_WITH_SPACE_DASH = auto_enum()
    REPLACE_WITH_SPACE_DASH_SPACE = auto_enum()

    def __str__(self) -> str:
        str_map = {
            ColonReplace.KEEP: "Keep",
            ColonReplace.DELETE: "Delete",
            ColonReplace.REPLACE_WITH_DASH: "Replace with dash",
            ColonReplace.REPLACE_WITH_SPACE_DASH: "Replace with space dash",
            ColonReplace.REPLACE_WITH_SPACE_DASH_SPACE: "Replace with space dash space",
        }
        return str_map[self]


class UnfilledTokenRemoval(CaseInsensitiveEnum):
    KEEP = auto_enum()
    TOKEN_ONLY = auto_enum()
    ENTIRE_LINE = auto_enum()

    def __str__(self) -> str:
        str_map = {
            UnfilledTokenRemoval.KEEP: "Keep",
            UnfilledTokenRemoval.TOKEN_ONLY: "Token only",
            UnfilledTokenRemoval.ENTIRE_LINE: "Entire line",
        }
        return str_map[self]
