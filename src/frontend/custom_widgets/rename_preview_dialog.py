from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from src.frontend.custom_widgets.basic_code_editor import CodeEditor
from src.frontend.utils import set_top_parent_geometry


class RenamePreviewDialog(QDialog):
    """Dialog to preview file/folder renames with diff-style visualization."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rename Preview")
        self.setWindowFlag(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        set_top_parent_geometry(self)

        header_label = QLabel(
            text="<h2 style='margin: 0; padding: 0;'>📝 Rename Preview</h2>"
            "<p style='margin-top: 8px;'>Review the changes below. "
            "Click <b>Rename</b> to apply or <b>Cancel</b> to go back and make changes.</p>",
            parent=self,
            wordWrap=True,
        )

        self.text_viewer = CodeEditor(
            line_numbers=False, wrap_text=True, mono_font=True, parent=self
        )
        self.text_viewer.setReadOnly(True)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        rename_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        rename_button.setText("Rename")
        rename_button.setDefault(True)

        cancel_button = self.button_box.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_button.setText("Cancel")

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(header_label)
        layout.addWidget(self.text_viewer)
        layout.addWidget(self.button_box)

    def set_renames(self, rename_map: dict[Path, Path]) -> None:
        """Populate the viewer with diff-style rename preview.

        Args:
            rename_map: Dictionary mapping original paths to renamed paths
        """
        if not rename_map:
            self.text_viewer.setPlainText("No renames detected")
            self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return

        # separate folders and files
        folder_renames: dict[Path, Path] = {}
        file_renames: dict[Path, Path] = {}

        for src, dest in rename_map.items():
            if src.parent != dest.parent:
                # folder rename detected
                folder_renames[src.parent] = dest.parent
            if src != dest:
                # file rename
                file_renames[src] = dest

        cursor = self.text_viewer.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)

        # format definitions
        bold_format = QTextCharFormat()
        bold_font = QFont()
        bold_font.setBold(True)
        bold_format.setFont(bold_font)

        removed_format = QTextCharFormat()
        removed_format.setBackground(QColor(255, 200, 200))  # light red

        added_format = QTextCharFormat()
        added_format.setBackground(QColor(200, 255, 200))  # light green

        normal_format = QTextCharFormat()

        # add folder renames
        if folder_renames:
            cursor.insertText("📁 FOLDERS:\n", bold_format)
            cursor.insertText("\n", normal_format)

            for old_folder, new_folder in sorted(folder_renames.items()):
                old_diff, new_diff = self._get_diff_parts(
                    old_folder.name, new_folder.name
                )

                # old name (removed)
                cursor.insertText("  - ", normal_format)
                self._insert_diff_text(cursor, old_diff, removed_format, normal_format)
                cursor.insertText("\n", normal_format)

                # new name (added)
                cursor.insertText("  + ", normal_format)
                self._insert_diff_text(cursor, new_diff, added_format, normal_format)
                cursor.insertText("\n\n", normal_format)

        # add file renames
        if file_renames:
            if folder_renames:
                cursor.insertText("\n", normal_format)

            cursor.insertText("📄 FILES:\n", bold_format)
            cursor.insertText("\n", normal_format)

            for old_file, new_file in sorted(file_renames.items()):
                old_diff, new_diff = self._get_diff_parts(old_file.name, new_file.name)

                # old name (removed)
                cursor.insertText("  - ", normal_format)
                self._insert_diff_text(cursor, old_diff, removed_format, normal_format)
                cursor.insertText("\n", normal_format)

                # new name (added)
                cursor.insertText("  + ", normal_format)
                self._insert_diff_text(cursor, new_diff, added_format, normal_format)
                cursor.insertText("\n\n", normal_format)

        # move cursor to start
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.text_viewer.setTextCursor(cursor)

    def _get_diff_parts(
        self, old: str, new: str
    ) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
        """Get diff parts with (text, is_changed) tuples.

        Returns:
            Tuple of (old_parts, new_parts) where each is list of (text, is_changed)
        """
        # find common prefix
        i = 0
        while i < min(len(old), len(new)) and old[i] == new[i]:
            i += 1

        # find common suffix
        j = 0
        while j < min(len(old), len(new)) - i and old[-(j + 1)] == new[-(j + 1)]:
            j += 1

        prefix = old[:i]
        suffix = old[len(old) - j :] if j else ""

        old_middle = old[i : len(old) - j if j else len(old)]
        new_middle = new[i : len(new) - j if j else len(new)]

        # build parts: (text, is_changed)
        old_parts = []
        if prefix:
            old_parts.append((prefix, False))
        if old_middle:
            old_parts.append((old_middle, True))
        if suffix:
            old_parts.append((suffix, False))

        new_parts = []
        if prefix:
            new_parts.append((prefix, False))
        if new_middle:
            new_parts.append((new_middle, True))
        if suffix:
            new_parts.append((suffix, False))

        return old_parts, new_parts

    def _insert_diff_text(
        self,
        cursor: QTextCursor,
        parts: list[tuple[str, bool]],
        highlight_format: QTextCharFormat,
        normal_format: QTextCharFormat,
    ) -> None:
        """Insert text with appropriate formatting for changed/unchanged parts."""
        for text, is_changed in parts:
            if is_changed:
                cursor.insertText(text, highlight_format)
            else:
                cursor.insertText(text, normal_format)
