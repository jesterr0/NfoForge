import sys
from collections.abc import Sequence
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QToolButton,
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QCursor, QCloseEvent, QShowEvent


class CustomPopup(QWidget):
    show_event = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)

        self.list_widget = QListWidget(self)
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # self.list_widget.setMaximumHeight(max_height)
        self.list_widget.setSizeAdjustPolicy(
            QListWidget.SizeAdjustPolicy.AdjustToContents
        )
        self.list_widget.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.MinimumExpanding
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list_widget, stretch=1)
        self.setLayout(layout)

    def showEvent(self, event: QShowEvent) -> None:
        self.show_event.emit(True)
        super().showEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.show_event.emit(False)
        super().closeEvent(event)

    def toggle_popup(self, widget: QWidget | None = None) -> None:
        if self.isVisible():
            self.close()
        else:
            if not widget:
                self.move(QCursor.pos())
                self.show()
            else:
                widget_pos = widget.mapToGlobal(widget.rect().bottomLeft())
                self.move(widget_pos)
                self.show()

    def update_menu(self, items: Sequence[tuple[str, bool]]) -> None:
        self.list_widget.clear()

        for item in items:
            text, toggle = item
            list_item = QListWidgetItem(text)
            list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if toggle:
                list_item.setCheckState(Qt.CheckState.Checked)
            else:
                list_item.setCheckState(Qt.CheckState.Unchecked)
            self.list_widget.addItem(list_item)

    def get_checked_items(self) -> list[str | None]:
        checked_items = []
        for index in range(self.list_widget.count()):
            list_item = self.list_widget.item(index)
            if list_item.checkState() == Qt.CheckState.Checked:
                checked_items.append(list_item.text())
        return checked_items


class CustomButtonMenu(QToolButton):
    item_changed = Signal(tuple)

    def __init__(
        self,
        text: str | None = None,
        popup_at_mouse: bool = False,
        max_pop_up_height: int = 250,
        enforce_one_checked: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setCheckable(True)
        if text:
            self.setText(text)

        self.popup_at_mouse = popup_at_mouse
        self.enforce_one_checked = enforce_one_checked

        self.popup = CustomPopup(self)
        self.popup.setMaximumHeight(max_pop_up_height)
        self.popup.show_event.connect(self._toggle)
        self.popup.list_widget.itemChanged.connect(self._item_changed)

        self.clicked.connect(self._clicked)

    def update_items(self, items: Sequence[tuple[str, bool]]) -> None:
        self.popup.update_menu(items)

    def get_checked_items(self) -> list[str | None]:
        return self.popup.get_checked_items()

    def _clicked(self) -> None:
        if self.popup_at_mouse:
            self.popup.toggle_popup()
        else:
            self.popup.toggle_popup(self)

    @Slot(bool)
    def _toggle(self, checked: bool) -> None:
        self.setChecked(checked)

    @Slot(object)
    def _item_changed(self, item: QListWidgetItem) -> None:
        # if enforcing one checked item, prevent unchecking the last checked item
        if self.enforce_one_checked:
            checked_items = [
                i
                for i in range(self.popup.list_widget.count())
                if self.popup.list_widget.item(i).checkState() == Qt.CheckState.Checked
            ]

            # if there are no checked items after this change, revert the check state
            if len(checked_items) == 0:
                self.popup.list_widget.itemChanged.disconnect(self._item_changed)
                item.setCheckState(Qt.CheckState.Checked)
                self.popup.list_widget.itemChanged.connect(self._item_changed)
                return

        self.item_changed.emit(
            (item.text(), True if item.checkState() == Qt.CheckState.Checked else False)
        )


examples = [
    ("Value1", True),
    ("Value2", False),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Custom Popup Example")
        self.setGeometry(100, 100, 400, 300)

        button_menu = CustomButtonMenu("Click", False, parent=self)
        button_menu.update_items(examples)
        button_menu.get_checked_items()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
