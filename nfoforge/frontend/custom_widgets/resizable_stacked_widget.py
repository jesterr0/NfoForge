from PySide6.QtCore import QSize
from PySide6.QtWidgets import QStackedWidget, QWidget


class ResizableStackedWidget(QStackedWidget):
    """QStackedWidget that dynamically shrinks as needed to fit the contents"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

    def sizeHint(self) -> QSize:
        widget = self.currentWidget()
        return widget.sizeHint() if widget is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        widget = self.currentWidget()
        return (
            widget.minimumSizeHint()
            if widget is not None
            else super().minimumSizeHint()
        )
