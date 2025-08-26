from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.frontend.custom_widgets.dnd_factory import DNDLineEdit
from src.frontend.custom_widgets.file_tree import FileSystemTreeView
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap


class ComparisonFileMatcher(QWidget):
    """
    Widget for selecting a source file and matching it with a single file from a directory tree.
    """

    # emitted when user accepts a match
    match_accepted = Signal(object, object)  # Path(source_file), Path(selected_file)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("comparisonFileMatcher")
        self._root_path: Path | None = None

        self.source_line_edit = DNDLineEdit(
            self, readOnly=True, placeholderText="Open source file..."
        )
        self.source_line_edit.setPlaceholderText("Open source file...")
        self.source_line_edit.set_extensions(("*",))
        self.source_line_edit.dropped.connect(self._dropped_file_source)

        self.browse_btn = QToolButton(self)
        self.browse_btn.setToolTip("Open source file")
        QTAThemeSwap().register(
            self.browse_btn, "ph.file-arrow-down-light", icon_size=QSize(24, 24)
        )
        self.browse_btn.clicked.connect(self._browse_source_file)

        self.file_tree = FileSystemTreeView(read_only=True, parent=self)
        self.file_tree.selectionModel().selectionChanged.connect(
            self.update_accept_button
        )

        self.accept_btn = QToolButton(self)
        self.accept_btn.setToolTip("Accept match")
        QTAThemeSwap().register(
            self.accept_btn, "ph.check-light", icon_size=QSize(24, 24)
        )
        self.accept_btn.clicked.connect(self._accept_match)
        self.accept_btn.setEnabled(False)

        source_layout = QHBoxLayout()
        source_layout.addWidget(self.source_line_edit, 1)
        source_layout.addWidget(self.browse_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Source File:", self))
        layout.addLayout(source_layout)
        layout.addWidget(QLabel("Select matching file:", self))
        layout.addWidget(self.file_tree)
        layout.addWidget(self.accept_btn, alignment=Qt.AlignmentFlag.AlignRight)

    @Slot(list)
    def _dropped_file_source(self, val: list[Path]) -> None:
        if val:
            self.source_line_edit.setText(str(val[0]))
            self.update_accept_button()

    @Slot()
    def _browse_source_file(self) -> None:
        """Open file dialog to select source file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Source File", "", "All Files (*.*)"
        )

        if file_path:
            self.source_line_edit.setText(file_path)
            self.update_accept_button()

    def set_directory_tree(self, root_path: Path) -> None:
        """Set the root directory to display in the tree."""
        self._root_path = root_path
        # always use read_only=True for single selection
        self.file_tree.read_only = True
        self.file_tree.build_tree(root_path)
        self.file_tree.expandAll()
        self.update_accept_button()

    def get_source_file(self) -> str | None:
        """Get the current source file path."""
        text = self.source_line_edit.text().strip()
        return text if text else None

    def get_selected_file(self) -> str | None:
        """Get the currently selected file from the tree."""
        selection_model = self.file_tree.selectionModel()
        if selection_model.hasSelection():
            selected_indexes = selection_model.selectedIndexes()
            if selected_indexes:
                # get the first column index (name column)
                index = selected_indexes[0]
                if index.column() != 0:
                    # get the corresponding item in the first column
                    index = self.file_tree.model().index(index.row(), 0, index.parent())

                # get the item text (filename) from the model
                item_text = self.file_tree.model().data(
                    index, Qt.ItemDataRole.DisplayRole
                )
                if item_text and item_text in self.file_tree.items:
                    file_path = self.file_tree.items[item_text]
                    # only return if it's a file, not a directory
                    if Path(file_path).is_file():
                        return file_path

    @Slot()
    def _accept_match(self) -> None:
        """Accept the current match and emit signal."""
        source_file = self.get_source_file()
        selected_file = self.get_selected_file()

        if source_file and selected_file:
            self.match_accepted.emit(Path(source_file), Path(selected_file))

    @Slot()
    def update_accept_button(self) -> None:
        """Update the enabled state of the accept button."""
        has_source = bool(self.get_source_file())
        has_selection = bool(self.get_selected_file())
        self.accept_btn.setEnabled(has_source and has_selection)
