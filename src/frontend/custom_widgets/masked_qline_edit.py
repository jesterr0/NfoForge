from PySide6.QtWidgets import QWidget, QLineEdit
from PySide6.QtGui import QEnterEvent
from PySide6.QtCore import QEvent


class MaskedQLineEdit(QLineEdit):
    def __init__(self, parent: QWidget = None, masked: bool = False, **kwargs) -> None:
        super().__init__(parent, **kwargs)

        if masked:
            self.setEchoMode(QLineEdit.EchoMode.Password)
            self.enterEvent = self.customEnterEvent
            self.leaveEvent = self.customLeaveEvent

    def customEnterEvent(self, _: QEnterEvent) -> None:
        self.setEchoMode(QLineEdit.EchoMode.Normal)

    def customLeaveEvent(self, _: QEvent) -> None:
        self.setEchoMode(QLineEdit.EchoMode.Password)
