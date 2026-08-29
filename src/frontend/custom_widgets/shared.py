from PySide6.QtGui import QFont


def scaled_font(
    base_font: QFont,
    factor: float,
    *,
    bold: bool = False,
) -> QFont:
    """Return a scaled copy of ``base_font``.

    The font size is scaled relative to the supplied font, preserving whether
    it uses pixel-based or point-based sizing.

    Args:
        base_font: Font to copy and scale.
        factor: Multiplier applied to the font size.
        bold: Whether the returned font should be bold.

    Returns:
        A new ``QFont`` with the scaled size and requested weight.
    """
    font = QFont(base_font)

    if base_font.pixelSize() > 0:
        font.setPixelSize(round(base_font.pixelSize() * factor))
    else:
        font.setPointSizeF(base_font.pointSizeF() * factor)

    font.setBold(bold)
    return font
