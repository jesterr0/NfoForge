from os import PathLike
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QIcon, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QFileIconProvider, QFrame, QHeaderView, QTreeView, QWidget

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
        self,
        path: PathLike[str] | Path | None = None,
        read_only: bool = True,
        parent: QWidget | None = None,
        **kwargs,
    ) -> None:
        super().__init__(parent=parent, **kwargs)
        self.setObjectName("fileSystemTreeView")
        self.setFrameShape(QFrame.Shape.Box)
        self.setFrameShadow(QFrame.Shadow.Sunken)

        self.read_only = read_only

        self.items = {}

        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(("Name", "Size", "Ext"))
        self.setModel(self._model)

        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        self.icon_provider = QFileIconProvider()

        if path:
            self.build_tree(path)

        self._model.itemChanged.connect(self.handle_item_changed)

    def clear_tree(self) -> None:
        self._model.removeRows(0, self._model.rowCount())

    def build_tree(self, path: PathLike[str] | Path | None) -> None:
        """
        Build the tree starting from the given path. The root directory is always shown as the top-level node.
        """
        self.clear_tree()
        if path:
            path = Path(path)
            root_item = self.create_row_item(path)
            self.items[path.name] = str(path)
            ext = "" if path.is_dir() else path.suffix.replace(".", "")
            self._model.invisibleRootItem().appendRow(
                (root_item, QStandardItem(""), QStandardItem(ext))
            )
            if path.is_dir():
                self.add_items(root_item, path)

    def add_items(self, parent_item, path) -> None:
        path = Path(path)
        directories = []
        files = []

        # separate directories and files
        if path.is_dir():
            for item_path in sorted(
                path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
            ):
                if item_path.is_dir():
                    directories.append(item_path)
                else:
                    files.append(item_path)
        else:
            files.append(path)

        # add directories first
        for item_path in directories:
            item = self.create_row_item(item_path)
            self.items[item_path.name] = str(item_path)
            parent_item.appendRow((item, QStandardItem(""), QStandardItem("")))
            # recursively add child items
            self.add_items(item, item_path)

        # add files second
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
            item.setCheckState(Qt.CheckState.Checked)
        item.setEditable(False)
        item.setSelectable(True)
        item.setToolTip(str(item_path.name))
        if item_path.is_dir():
            item.setIcon(self.icon_provider.icon(QFileIconProvider.IconType.Folder))
        else:
            item.setIcon(self.get_icon(item_path))
        return item

    @Slot(QStandardItem)
    def handle_item_changed(self, item: QStandardItem) -> None:
        self.update_child_items_check_state(item, item.checkState())

    def update_child_items_check_state(
        self, item: QStandardItem, check_state: Qt.CheckState
    ) -> None:
        if item.hasChildren():
            for row in range(item.rowCount()):
                child_item = item.child(row)
                child_item.setCheckState(check_state)
                self.update_child_items_check_state(child_item, check_state)
        else:
            item.setCheckState(check_state)

    def get_checked_items(self) -> list[dict[str, Any]]:
        """
        Generates a list of selected items with their full paths, relative paths, sizes in bytes,
        and directory status. In read_only mode, returns all items as checked.
        """
        checked_items: list[dict[str, Any]] = []
        root_item = self._model.invisibleRootItem()
        # find the root path for relative path calculation
        if self.items:
            # the first value in self.items is the root
            root_path_str = next(iter(self.items.values()))
            root_path = Path(root_path_str)
        else:
            root_path = None
        self._collect_checked_items(
            root_item, checked_items, root_path, treat_all_checked=self.read_only
        )
        return checked_items

    def _collect_checked_items(
        self,
        parent_item: QStandardItem,
        checked_items: list,
        root_path: Path | None,
        treat_all_checked: bool = False,
    ) -> None:
        for row in range(parent_item.rowCount()):
            item = parent_item.child(row)
            is_checked = treat_all_checked or item.checkState() == Qt.CheckState.Checked
            if is_checked:
                path_str = self.items[item.text()]
                path_obj = Path(path_str)
                try:
                    size = path_obj.stat().st_size
                except Exception:
                    size = 0
                is_dir = path_obj.is_dir()
                if root_path:
                    try:
                        relative_path = str(path_obj.relative_to(root_path))
                    except ValueError:
                        relative_path = path_obj.name
                else:
                    relative_path = path_obj.name
                checked_items.append(
                    {
                        "path": path_str,
                        "relative_path": relative_path,
                        "size": size,
                        "is_dir": is_dir,
                    }
                )
            self._collect_checked_items(
                item, checked_items, root_path, treat_all_checked
            )

    def get_icon(self, item_path: Path) -> QIcon:
        """Returns the appropriate icon for the given file based on its extension."""
        from PySide6.QtCore import QFileInfo

        # first try to get the actual system icon
        try:
            file_info = QFileInfo(str(item_path))
            system_icon = self.icon_provider.icon(file_info)
            # check if we got a meaningful icon (not just the generic file icon)
            if not system_icon.isNull():
                return system_icon
        except Exception:
            pass

        # fallback to custom icons for specific types
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
        except FileNotFoundError:
            pass

        # final fallback to generic file icon
        return self.icon_provider.icon(QFileIconProvider.IconType.File)

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
