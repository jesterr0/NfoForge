from os import PathLike
from pathlib import Path
from typing import List, Optional
from PySide6.QtWidgets import (
    QTreeView,
    QWidget,
    QFileIconProvider,
    QHeaderView,
    QFrame,
)
from PySide6.QtGui import QStandardItemModel, QStandardItem, QIcon
from PySide6.QtCore import Qt, Slot

from src.backend.utils.working_dir import RUNTIME_DIR


class FileSystemTreeView(QTreeView):
    """
    Widget designed to select file types you want with a public method
    `get_checked_items` that returns a list of paths based on the selected
    items.
    """

    VIDEO_EXTENSIONS = (".mp4", ".mkv", ".hevc", ".h264", "h265", ".vp9", ".av1")
    AUDIO_EXTENSION = (".ac3", ".ec3", ".eac3", ".thd", ".flac", ".aac", ".opus")
    TEXT_EXTENSIONS = (".txt", ".log", ".vpy", ".avs")
    INDEX_EXTENSIONS = (".ffindex", ".lwi", ".d2v")
    IMAGE_DIR = RUNTIME_DIR / "images"

    def __init__(
        self, path: PathLike[str] = None, read_only: bool = True, parent: QWidget = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("fileSystemTreeView")
        self.setFrameShape(QFrame.Shape.Box)
        self.setFrameShadow(QFrame.Shadow.Sunken)

        self.read_only = read_only

        self.items = {}

        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(("Name", "Size", "Ext"))
        self.setModel(self.model)

        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)

        self.icon_provider = QFileIconProvider()

        if path:
            self.build_tree(path)

        self.model.itemChanged.connect(self.handle_item_changed)

    def clear_tree(self) -> None:
        self.model.removeRows(0, self.model.rowCount())

    def build_tree(self, path: Optional[Path]) -> None:
        if path:
            parent_item = self.model.invisibleRootItem()
            self.add_items(parent_item, path)

    def add_items(self, parent_item, path) -> None:
        path = Path(path)
        directories = []
        files = []

        # Separate directories and files
        if path.is_dir():
            for item_path in path.iterdir():
                if item_path.is_dir():
                    directories.append(item_path)
                else:
                    files.append(item_path)
        else:
            files.append(path)

        # Add directories first
        for item_path in directories:
            item = self.create_row_item(item_path)
            self.items[item_path.name] = str(item_path)

            # Recursively add child items
            self.add_items(item, item_path)
            parent_item.appendRow(item)

        # Add files second
        for item_path in files:
            item = self.create_row_item(item_path)
            size_item = QStandardItem(self.get_file_size_in_gb(item_path))
            suffix_item = QStandardItem(item_path.suffix.replace(".", ""))

            self.items[item_path.name] = str(item_path)
            parent_item.appendRow((item, size_item, suffix_item))

    def create_row_item(self, item_path: Path) -> QStandardItem:
        item = QStandardItem(item_path.name)
        if self.read_only:
            item.setCheckable(False)
        else:
            item.setCheckable(True)
            item.setCheckState(Qt.Checked)
        item.setEditable(False)
        item.setSelectable(True)
        item.setToolTip(str(item_path.name))
        if item_path.is_dir():
            item.setIcon(self.icon_provider.icon(QFileIconProvider.Folder))
        else:
            item.setIcon(self.get_custom_icon(item_path))
        return item

    @Slot(QStandardItem)
    def handle_item_changed(self, item: QStandardItem) -> None:
        self.update_child_items_check_state(item, item.checkState())

    def update_child_items_check_state(
        self, item: QStandardItem, check_state: int
    ) -> None:
        if item.hasChildren():
            for row in range(item.rowCount()):
                child_item = item.child(row)
                child_item.setCheckState(check_state)
                self.update_child_items_check_state(child_item, check_state)
        else:
            item.setCheckState(check_state)

    def get_checked_items(self) -> List[Optional[PathLike[str]]]:
        """
        Generates a list of selected items with their full paths

        Returns:
            List[Optional[PathLike[str]]]: Returns a list of PathLike strings.
        """
        checked_items = []
        root_item = self.model.invisibleRootItem()
        self._collect_checked_items(root_item, checked_items)
        return checked_items

    def _collect_checked_items(self, parent_item, checked_items):
        for row in range(parent_item.rowCount()):
            item = parent_item.child(row)
            if item.checkState() == Qt.Checked:
                checked_items.append(self.items[item.text()])
            self._collect_checked_items(item, checked_items)

    def get_custom_icon(self, item_path: Path) -> QIcon:
        """Returns the appropriate icon for the given file based on its extension."""
        try:
            if self.IMAGE_DIR.exists():
                icon_path = None
                file_extension = item_path.suffix
                if file_extension in self.VIDEO_EXTENSIONS:
                    icon_path = self.IMAGE_DIR / "vlc.png"
                elif file_extension in self.AUDIO_EXTENSION:
                    icon_path = self.IMAGE_DIR / "audio.png"
                elif file_extension in self.TEXT_EXTENSIONS:
                    icon_path = self.IMAGE_DIR / "script.png"
                elif file_extension in self.INDEX_EXTENSIONS:
                    icon_path = self.IMAGE_DIR / "index.png"
                elif file_extension == ".srt":
                    icon_path = self.IMAGE_DIR / "srt.png"
                elif file_extension == ".json":
                    icon_path = self.IMAGE_DIR / "json.png"
                elif file_extension == ".srip":
                    icon_path = self.IMAGE_DIR / "staxrip.ico"
                if icon_path and icon_path.exists():
                    return QIcon(str(icon_path))
            return self.icon_provider.icon(QFileIconProvider.File)
        except FileNotFoundError:
            return self.icon_provider.icon(QFileIconProvider.File)

    @staticmethod
    def get_file_size_in_gb(file_input: Path) -> str:
        """Returns the size of the file as a string in GB, MB, or KB."""
        file_size_bytes = file_input.stat().st_size
        file_size_gb = file_size_bytes / (1024**3)

        if file_size_gb >= 1:
            return f"{file_size_gb:.2f} GB"
        else:
            file_size_mb = file_size_bytes / (1024**2)
            if file_size_mb >= 1:
                return f"{file_size_mb:.2f} MB"
            else:
                file_size_kb = file_size_bytes / 1024
                return f"{file_size_kb:.2f} KB"
