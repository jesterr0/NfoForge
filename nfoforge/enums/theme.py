from enum import auto as auto_enum
from typing import override

from PySide6.QtGui import Qt

from nfoforge.enums import CaseInsensitiveEnum


class NfoForgeTheme(CaseInsensitiveEnum):
    AUTOMATIC = auto_enum()
    LIGHT = auto_enum()
    DARK = auto_enum()

    def theme(self) -> Qt.ColorScheme | None:
        qt_theme = Qt.ColorScheme
        theme_map = {
            NfoForgeTheme.AUTOMATIC: None,
            NfoForgeTheme.LIGHT: qt_theme.Light,
            NfoForgeTheme.DARK: qt_theme.Dark,
        }
        return theme_map[self]

    @override
    def __str__(self) -> str:
        str_map = {
            NfoForgeTheme.AUTOMATIC: "Automatic",
            NfoForgeTheme.LIGHT: "Light",
            NfoForgeTheme.DARK: "Dark",
        }
        return str_map[self]
