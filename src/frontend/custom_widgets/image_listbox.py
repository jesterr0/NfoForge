from PySide6.QtWidgets import QListWidget, QListWidgetItem, QFrame
from PySide6.QtGui import QIcon, QFontDatabase, QFont
from PySide6.QtCore import QSize, Qt

from pathlib import Path


class ThumbnailListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(250, 250))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setDragEnabled(False)
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFrameShape(QFrame.Shape.Box)
        self.setFrameShadow(QFrame.Shadow.Sunken)

    def add_thumbnail(self, image_path: Path):
        item = QListWidgetItem(QIcon(str(image_path)), "")
        self.addItem(item)

    def enable_mono_text(self) -> None:
        if "Fira Mono" in QFontDatabase().families():
            self.setFont(QFont("Fira Mono"))
        else:
            self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
