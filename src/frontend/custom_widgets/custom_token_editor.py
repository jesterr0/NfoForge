from collections.abc import Sequence
import re

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.backend.tokens import TokenSelection
from src.frontend.custom_widgets.basic_code_editor import CodeEditor


class ComboBoxDelegate(QStyledItemDelegate):
    def __init__(self, items: Sequence[str], parent=None):
        super().__init__(parent)
        self.items = items

    def createEditor(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        parent: QWidget,
        _option: QStyleOptionViewItem,
        _index: QModelIndex,
    ) -> QComboBox:
        combo = QComboBox(parent)
        combo.addItems(self.items)
        return combo

    def setEditorData(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, editor: QComboBox, index: QModelIndex
    ) -> None:
        value = index.model().data(index, Qt.ItemDataRole.EditRole)
        idx = editor.findText(value)
        if idx >= 0:
            editor.setCurrentIndex(idx)

    def setModelData(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, editor: QComboBox, model: QAbstractItemModel, index: QModelIndex
    ) -> None:
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


class CustomTokenEditor(QWidget):
    INVALID_COLOR = QColor(255, 0, 0, 150)
    VALID_COLOR = QColor(0, 0, 0, 0)

    save_changes_now = Signal(object)

    def __init__(
        self,
        token_types: Sequence[str],
        token_prefix: str = "usr_",
        hide_save_btn: bool = False,
        hide_expand_editor: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("customTokenEditor")

        self.token_types = token_types
        self.token_prefix = token_prefix

        self.value_map = {}
        self._updating = False
        self._delete_timer: QTimer | None = None
        self._delete_confirm_row: int | None = None

        self.table = QTableWidget(rowCount=0, columnCount=2, parent=self)
        self.table.setHorizontalHeaderLabels(["Token", "Type"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(self.table.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            self.table.EditTrigger.DoubleClicked
            | self.table.EditTrigger.SelectedClicked
            | self.table.EditTrigger.EditKeyPressed
        )
        self.table.setItemDelegateForColumn(1, ComboBoxDelegate(self.token_types, self))
        self.table.setFrameShape(QFrame.Shape.Box)
        self.table.setFrameShadow(QFrame.Shadow.Sunken)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemChanged.connect(self._on_item_changed)

        self.value_edit = CodeEditor(mono_font=True, parent=self)
        self.value_edit.setFrameShape(QFrame.Shape.Box)
        self.value_edit.setFrameShadow(QFrame.Shadow.Sunken)
        self.value_edit.textChanged.connect(self._on_value_changed)

        self.add_btn = QPushButton("Add", self)
        self.add_btn.clicked.connect(self._add_token)

        self.delete_btn = QPushButton("Delete", self)
        self.delete_btn.clicked.connect(self._delete_token)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.delete_btn)

        if not hide_save_btn:
            self.save_btn = QPushButton("Save Now")
            self.save_btn.setToolTip(
                "Saves changes now (saves to config and updates UI elements without "
                "using the Apply button)"
            )
            self.save_btn.clicked.connect(self._save_now)
            btn_layout.addWidget(self.save_btn)

        if not hide_expand_editor:
            self.expand_btn = QPushButton("Expand Editor", self)
            self.expand_btn.clicked.connect(self._expand_editor)
            btn_layout.addWidget(self.expand_btn)

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.value_edit)
        right_layout.addLayout(btn_layout)

        main_layout = QHBoxLayout(self)
        main_layout.addWidget(self.table, stretch=1)
        main_layout.addLayout(right_layout, stretch=1)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        # enforce format for col 1
        if item.column() == 0:
            text = item.text()
            # force lowercase and underscores only
            filtered = re.sub(r"[^a-z_]", "", text.lower())
            if text != filtered:
                item.setText(filtered)
                text = filtered
            # highlight row if not starting with the token prefix or contains invalid chars
            row = item.row()
            valid = text.startswith(self.token_prefix) and re.fullmatch(
                r"[a-z_]+", text
            )
            color = self.INVALID_COLOR if not valid else self.VALID_COLOR
            for col in range(self.table.columnCount()):
                cell = self.table.item(row, col)
                if cell:
                    cell.setBackground(color)

            # set tooltip only on the name column
            if not valid:
                item.setToolTip(
                    f"Invalid token (must start with {self.token_prefix} and only contain "
                    "lowercase letters and underscores)"
                )
            else:
                item.setToolTip("")

    def _on_selection_changed(self) -> None:
        selected = self.table.selectedItems()
        if selected:
            row = self.table.currentRow()
            self.value_edit.setPlainText(self.value_map.get(row, ""))
        else:
            self.value_edit.clear()

    def _on_value_changed(self) -> None:
        if self._updating:
            return
        row = self.table.currentRow()
        if row >= 0:
            self.value_map[row] = self.value_edit.toPlainText()

    def _add_token(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem("usr_new_token"))
        type_item = QTableWidgetItem(self.token_types[0])
        self.table.setItem(row, 1, type_item)
        self.value_map[row] = ""
        self.table.selectRow(row)

    def _delete_token(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return

        # Confirm? timer logic
        if not self._delete_confirm_row or self._delete_confirm_row != row:
            self.delete_btn.setText("Confirm?")
            self._delete_confirm_row = row
            if self._delete_timer:
                self._delete_timer.stop()

            self._delete_timer = QTimer(self)
            self._delete_timer.setSingleShot(True)
            self._delete_timer.timeout.connect(self._reset_delete_button)
            self._delete_timer.start(3000)

            # lock selection: disable table until timer is up or delete is confirmed
            self.table.setEnabled(False)
            return

        # if already in confirm state, delete
        self.table.removeRow(row)
        self.value_map.pop(row, None)
        self.value_map = {
            i: self.value_map.get(i, "") for i in range(self.table.rowCount())
        }
        self.value_edit.clear()
        self.delete_btn.setText("Delete")
        self._delete_confirm_row = None
        if self._delete_timer:
            self._delete_timer.stop()
        self.table.setEnabled(True)

    def _reset_delete_button(self) -> None:
        self.delete_btn.setText("Delete")
        self._delete_confirm_row = None
        self.table.setEnabled(True)

    @Slot()
    def _save_now(self) -> None:
        data = self.save_all()
        if data:
            self.save_changes_now.emit(data)

    def save_all(self) -> dict[str, tuple[str, str]] | None:
        """Save all tokens returning the output, if None is returned there was an error."""
        tokens = {}

        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            type_item = self.table.item(row, 1)
            name = name_item.text() if name_item else ""
            ttype = type_item.text() if type_item else self.token_types[0]

            if TokenSelection(ttype) is TokenSelection.FILE_TOKEN:
                lines = str(self.value_map.get(row, "")).splitlines(False)
                line_len = len(lines)
                if line_len > 1:
                    QMessageBox.warning(
                        self,
                        "Warning",
                        f"Token '{name}' is set to {TokenSelection.FILE_TOKEN} but has a multiline "
                        f"output. {TokenSelection.FILE_TOKEN} should be a single line. This must be "
                        "corrected to continue saving.",
                    )
                    return
                if line_len < 1:  # skip empty tokens
                    continue
                value = lines[0]
            else:
                value = self.value_map.get(row, "")

            if name and name.startswith(self.token_prefix):
                tokens[name] = (value, ttype)

        self.tokens = tokens

        return tokens

    def get_tokens(self) -> dict[str, tuple[str, str]]:
        return dict(self.tokens)

    def load_tokens(self, tokens: dict[str, tuple[str, str]]) -> None:
        """
        Load tokens into the table. tokens: {token_name: (value, token_type)}
        """
        self.table.setRowCount(0)
        self.value_map.clear()
        for i, (name, (value, ttype)) in enumerate(tokens.items()):
            self.table.insertRow(i)
            name_item = QTableWidgetItem(name)
            type_item = QTableWidgetItem(ttype)
            self.table.setItem(i, 0, name_item)
            self.table.setItem(i, 1, type_item)
            self.value_map[i] = value

            # re-validate row highlight
            self._on_item_changed(name_item)
        if tokens:
            self.table.selectRow(0)
            self.value_edit.setPlainText(self.value_map.get(0, ""))
        else:
            self.value_edit.clear()

    def reset(self) -> None:
        self.table.setRowCount(0)
        self.value_map.clear()
        self.value_edit.clear()

    def _expand_editor(self) -> None:
        dlg = QDialog(self, sizeGripEnabled=True)
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        row = self.table.currentRow()
        # Get token name for dialog title if available
        if row >= 0:
            name_item = self.table.item(row, 0)
            token_name = name_item.text() if name_item else None
        else:
            token_name = None
        title = "Edit Token Value"
        if token_name:
            title = f"{title} ({token_name})"
        dlg.setWindowTitle(title)
        parent_widget = self.parentWidget()
        if parent_widget is not None:
            dlg.resize(parent_widget.size())
        else:
            dlg.resize(700, 500)
        layout = QVBoxLayout(dlg)
        editor = CodeEditor(mono_font=True, parent=dlg)
        editor.setPlainText(self.value_edit.toPlainText())
        layout.addWidget(editor)
        btn = QPushButton("Okay", dlg)
        btn.setMaximumWidth(120)
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.value_edit.setPlainText(editor.toPlainText())


if __name__ == "__main__":
    import sys

    blah = {
        "usr_new_token": ("123", "FileToken"),
        "usr_blah": (
            "123 Howdy! This is the new custom token setup :)\n\nMulti line support as needed too!",
            "NfoToken",
        ),
        "usr_yay": ("more random data", "NfoToken"),
        "usr_nah": ("random data", "FileToken"),
    }

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = CustomTokenEditor(token_types=[x for x in TokenSelection])
    w.load_tokens(blah)
    w.show()
    sys.exit(app.exec())
