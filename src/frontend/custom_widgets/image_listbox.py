from PySide6.QtWidgets import QListWidget, QListWidgetItem
from PySide6.QtGui import QIcon
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

    def add_thumbnail(self, image_path: Path):
        item = QListWidgetItem(QIcon(str(image_path)), "")
        self.addItem(item)
