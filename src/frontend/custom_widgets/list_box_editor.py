from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.frontend.custom_widgets.basic_code_editor import CodeEditor


class ListBoxEditor(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("listBoxEditor")

        self.data = {}

        self.listbox = QListWidget(self)
        self.listbox.setFrameShape(QFrame.Shape.Box)
        self.listbox.setFrameShadow(QFrame.Shadow.Sunken)
        self.listbox.currentItemChanged.connect(self._on_item_selected)

        self.editor = CodeEditor(pop_out_expansion=True, parent=self)

        self.main_layout = QHBoxLayout(self)
        self.main_layout.addWidget(self.listbox, stretch=1)
        self.main_layout.addWidget(self.editor, stretch=3)

    def load_items(self, items: Sequence[str] | dict[str, Any]) -> None:
        self.listbox.clear()
        if isinstance(items, dict):
            self.data = items
            self.listbox.addItems(items.keys())
        else:
            self.data = {token: "" for token in items}
            self.listbox.addItems(items)
        if items:
            self.listbox.setCurrentRow(0)

    def get_data(self) -> dict[str, Any]:
        # save current editor content before returning
        current_item = self.listbox.currentItem()
        if current_item:
            self.data[current_item.text()] = self.editor.toPlainText()
        return dict(self.data)

    def get_item_widget(self, key: str) -> QListWidgetItem | None:
        """Return the QListWidgetItem for the given token key, or None if not found."""
        items = self.listbox.findItems(key, Qt.MatchFlag.MatchExactly)
        return items[0] if items else None

    @Slot(QListWidgetItem, QListWidgetItem)
    def _on_item_selected(
        self, current: QListWidgetItem, previous: QListWidgetItem
    ) -> None:
        if previous:
            prev_token = previous.text()
            self.data[prev_token] = self.editor.toPlainText()
        if current:
            token = current.text()
            self.editor.setPlainText(self.data.get(token, ""))


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QPushButton, QDialog
    import sys

    class TestDialog(QDialog):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Test")
            layout = QVBoxLayout(self)
            self.editor = ListBoxEditor()
            layout.addWidget(self.editor)
            # self.editor.load_items(["token1", "token2", "token3"])
            self.editor.load_items({"blah": "tom", "noob": "yes"})
            btn = QPushButton("Print Data")
            btn.clicked.connect(self.print_data)
            layout.addWidget(btn)
            self.setLayout(layout)

        def print_data(self):
            print(self.editor.get_data())

    app = QApplication(sys.argv)
    app.setStyle("fusion")
    # app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    dlg = TestDialog()
    dlg.show()
    sys.exit(app.exec())
