from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLineEdit, QWidget
from typing_extensions import override


class MaskedQLineEdit(QLineEdit):
    def __init__(self, parent: QWidget | None = None, masked: bool = False) -> None:
        super().__init__(parent)
        self._masked = masked

        if self._masked:
            self.setEchoMode(QLineEdit.EchoMode.Password)

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._masked and event.button() == Qt.MouseButton.LeftButton:
            self.setEchoMode(QLineEdit.EchoMode.Normal)
        super().mousePressEvent(event)

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._masked:
            self.setEchoMode(QLineEdit.EchoMode.Password)
        super().mouseReleaseEvent(event)
