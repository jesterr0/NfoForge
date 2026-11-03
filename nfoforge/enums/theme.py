from enum import auto as auto_enum
from typing import override

from nfoforge.enums import CaseInsensitiveEnum


class NfoForgeTheme(CaseInsensitiveEnum):
    AUTOMATIC = auto_enum()
    LIGHT = auto_enum()
    DARK = auto_enum()

    @override
    def __str__(self) -> str:
        str_map = {
            NfoForgeTheme.AUTOMATIC: "Automatic",
            NfoForgeTheme.LIGHT: "Light",
            NfoForgeTheme.DARK: "Dark",
        }
        return str_map[self]
