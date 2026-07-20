from PySide6.QtCore import QEvent
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QLineEdit, QWidget
from typing_extensions import override


class MaskedQLineEdit(QLineEdit):
    def __init__(self, parent: QWidget | None = None, masked: bool = False) -> None:
        super().__init__(parent)
        self._masked = masked

        if self._masked:
            self.setEchoMode(QLineEdit.EchoMode.Password)

    @override
    def enterEvent(self, event: QEnterEvent) -> None:
        if self._masked:
            self.setEchoMode(QLineEdit.EchoMode.Normal)
        super().enterEvent(event)

    @override
    def leaveEvent(self, event: QEvent) -> None:
        if self._masked:
            self.setEchoMode(QLineEdit.EchoMode.Password)
        super().leaveEvent(event)
