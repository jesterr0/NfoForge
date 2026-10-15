from PySide6.QtGui import QFont, QFontDatabase


def monospace_font() -> QFont:
    """Return the preferred monospace font for editor-style widgets."""
    if "Fira Mono" in QFontDatabase.families():
        return QFont("Fira Mono")
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
