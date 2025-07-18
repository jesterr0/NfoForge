import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.frontend.custom_widgets.basic_code_editor import CodeEditor
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.utils import build_auto_theme_icon_buttons


class AddKeyDialog(QDialog):
    FIXED_WIDTH = 250

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
        )
        self.setModal(True)
        self.setFixedWidth(self.FIXED_WIDTH)

        frame = QFrame(self)
        frame.setFrameShape(QFrame.Shape.Box)
        frame.setFrameShadow(QFrame.Shadow.Sunken)

        self.key_edit = QLineEdit(frame, placeholderText="Input new...")
        self.key_edit.returnPressed.connect(self.accept)

        self.ok_btn = QPushButton("OK", frame)
        self.ok_btn.clicked.connect(self.accept)

        self.cancel_btn = QPushButton("Cancel", frame)
        self.cancel_btn.clicked.connect(self.reject)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)

        frame_layout = QVBoxLayout(frame)
        frame_layout.addWidget(self.key_edit)
        frame_layout.addLayout(btn_layout)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(frame)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.activateWindow()
        self.raise_()
        self.key_edit.setFocus()
        self.key_edit.selectAll()

    def get_key(self) -> str:
        return self.key_edit.text().strip()


class DictWidget(QWidget):
    def __init__(
        self, data: dict[str, str] | None = None, del_interval: int = 2500, parent=None
    ) -> None:
        super().__init__(parent)
        self.data = data if data is not None else {}
        self.keys = list(self.data.keys())
        self.adding_new = False
        self.last_idx = None
        self.del_interval = del_interval
        self.delete_timer = None
        self.delete_pending_idx = None
        self.original_text = None

        self.combo = CustomComboBox(
            completer=True, completer_strict=True, disable_mouse_wheel=True, parent=self
        )
        self.combo.addItems(self.keys)
        self.combo.currentIndexChanged.connect(self.update_text)

        self.add_btn: QToolButton = build_auto_theme_icon_buttons(
            QToolButton, "add_circle.svg", "addDictKey", 24, 24
        )
        self.add_btn.clicked.connect(self.add_item)

        self.del_btn: QToolButton = build_auto_theme_icon_buttons(
            QToolButton, "delete.svg", "delDictKey", 24, 24
        )
        self.del_btn.clicked.connect(self.handle_delete)

        self.text_box = CodeEditor(parent=self)

        self.top_layout = QHBoxLayout()
        self.top_layout.addWidget(self.combo)
        self.top_layout.addWidget(self.add_btn)
        self.top_layout.addWidget(self.del_btn)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addLayout(self.top_layout)
        self.main_layout.addWidget(self.text_box, stretch=1)

        # init text box
        self.update_text(0)

    def fill_data(self, data: dict[str, str]) -> None:
        self.save_current_key_value()
        self.data = data.copy()
        self.keys = list(self.data.keys())
        self.combo.clear()
        self.combo.addItems(self.keys)
        self.update_text(0)

    def get_data(self) -> dict[str, str]:
        self.save_current_key_value()
        return self.data.copy()

    def save_current_key_value(self) -> None:
        idx = self.combo.currentIndex()
        if 0 <= idx < len(self.keys):
            key = self.keys[idx]
            self.data[key] = self.text_box.toPlainText()

    def handle_delete(self) -> None:
        idx = self.combo.currentIndex()

        # second click within timer: delete
        if (
            self.delete_timer
            and self.delete_timer.isActive()
            and self.delete_pending_idx == idx
        ):
            self.delete_timer.stop()
            self.delete_timer = None
            self.delete_pending_idx = None
            self.del_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.del_btn.setText("")
            self.delete_item()
            return

        # first click: start timer and show confirm
        self.delete_pending_idx = idx
        self.del_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.del_btn.setText("Confirm?")
        if not self.delete_timer:
            self.delete_timer = QTimer(self)
            self.delete_timer.setSingleShot(True)
            self.delete_timer.timeout.connect(self.cancel_delete)
        self.delete_timer.start(self.del_interval)

    def cancel_delete(self) -> None:
        self.del_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.del_btn.setText("")
        self.delete_timer = None
        self.delete_pending_idx = None

    def add_item(self) -> None:
        # reset delete timer on add
        if self.delete_timer and self.delete_timer.isActive():
            self.delete_timer.stop()
            self.cancel_delete()
        self.save_current_key_value()

        # pop up dialog
        dialog = AddKeyDialog(self)
        cursor_pos = QCursor.pos()
        # clamp dialog position to stay on screen
        screen = QApplication.primaryScreen().geometry()
        x = max(0, cursor_pos.x() - dialog.FIXED_WIDTH)
        y = min(max(0, cursor_pos.y()), screen.height() - dialog.height())
        dialog.move(x, y)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            key = dialog.get_key()
            if not key:
                QMessageBox.warning(self, "Invalid Input", "Input cannot be empty.")
                return
            if key in self.data:
                QMessageBox.warning(self, "Duplicate Input", "Input already exists.")
                return
            self.data[key] = ""
            self.keys.append(key)
            self.combo.addItem(key)
            self.combo.setCurrentIndex(self.combo.count() - 1)  # select the new key
            self.text_box.clear()
            self.text_box.setFocus()

    def save_new_item(self) -> None:
        key = self.combo.currentText().strip()
        value = self.text_box.toPlainText()
        if not key:
            return
        if key in self.data:
            QMessageBox.warning(self, "Duplicate Key", "Key already exists.")
            return
        self.data[key] = value
        self.keys.append(key)
        self.combo.addItem(key)
        self.combo.setCurrentText(key)
        self.combo.setEditable(False)
        self.adding_new = False

    def delete_item(self) -> None:
        self.save_current_key_value()
        idx = self.combo.currentIndex()
        if 0 <= idx < len(self.keys):
            key = self.keys.pop(idx)
            self.data.pop(key, None)
            self.combo.removeItem(idx)
            self.update_text(self.combo.currentIndex())

    def update_text(self, idx) -> None:
        # reset delete timer on key change
        if self.delete_timer and self.delete_timer.isActive():
            self.delete_timer.stop()
            self.cancel_delete()

        # save previous key's value before switching, but not on first init
        if (
            self.last_idx is not None
            and self.last_idx != idx
            and 0 <= self.last_idx < len(self.keys)
        ):
            key = self.keys[self.last_idx]
            self.data[key] = self.text_box.toPlainText()

        # update text box for new key
        if 0 <= idx < len(self.keys):
            key = self.keys[idx]
            self.text_box.setPlainText(self.data.get(key, ""))
        else:
            self.text_box.clear()

        # update last_idx
        self.last_idx = idx

    def closeEvent(self, event) -> None:
        # timer cleanup
        if self.delete_timer and self.delete_timer.isActive():
            self.delete_timer.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    sample_data = {"Key1": "Value 1", "Key2": "Value 2", "Key3": "Value 3"}
    w = DictWidget(sample_data)
    w.resize(400, 300)
    w.show()
    sys.exit(app.exec())
