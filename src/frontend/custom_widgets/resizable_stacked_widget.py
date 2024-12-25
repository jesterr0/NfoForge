from PySide6.QtWidgets import QStackedWidget, QWidget
from PySide6.QtCore import QSize


class ResizableStackedWidget(QStackedWidget):
    """QStackedWidget that dynamically shrinks as needed to fit the contents"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

    def sizeHint(self) -> QSize:
        return self.currentWidget().sizeHint()

    def minimumSizeHint(self) -> QSize:
        return self.currentWidget().minimumSizeHint()
