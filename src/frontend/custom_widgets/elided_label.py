from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics, QResizeEvent
from PySide6.QtWidgets import QApplication, QLabel, QSizePolicy, QWidget

from src.frontend.custom_widgets.shared import scaled_font


class EllipsisLabel(QLabel):
    """QLabel that elides plain text (right-elide) when it doesn't fit."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        font_scale: float = 1.0,
        bold: bool | None = None,
        tool_tip: bool | None = None,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._font_scale = font_scale
        self._bold = bold
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.fontChanged.connect(self._apply_relative_font)
        self._apply_relative_font()
        self.setText(text)

    def setText(self, text: str) -> None:
        self._text = text
        self.updateText()

    def text(self) -> str:
        """Return the complete text, rather than the elided presentation."""
        return self._text

    def setFont(self, font: QFont | str | Sequence[str]) -> None:
        super().setFont(font)
        self.updateText()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.updateText()

    def updateText(self) -> None:
        metrics = QFontMetrics(self.font())

        elided = metrics.elidedText(
            self._text,
            Qt.TextElideMode.ElideRight,
            self.contentsRect().width(),
        )

        super().setText(elided)

    def _apply_relative_font(self, _font: QFont | None = None) -> None:
        if self._font_scale == 1.0 and self._bold is None:
            return

        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return

        base_font = app.font(self)
        self.setFont(
            scaled_font(
                base_font,
                self._font_scale,
                bold=base_font.bold() if self._bold is None else self._bold,
            )
        )
