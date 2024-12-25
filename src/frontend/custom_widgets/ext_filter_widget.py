from collections.abc import Iterable

from PySide6.QtWidgets import QWidget, QLabel, QLineEdit, QHBoxLayout, QFormLayout
from PySide6.QtCore import Slot

from src.frontend.custom_widgets.menu_button import CustomButtonMenu


class ExtFilterWidget(QWidget):
    """Widget to toggle accepted extensions"""

    def __init__(
        self,
        label_text: str,
        tool_tip: str | None = None,
        button_txt: str = "...",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        filtered_ext_basic_lbl = QLabel(label_text, self)
        if tool_tip:
            filtered_ext_basic_lbl.setToolTip(tool_tip)
        self.filtered_ext_basic_menu = CustomButtonMenu(
            text=button_txt,
            max_pop_up_height=350,
            enforce_one_checked=True,
            parent=self,
        )
        self.filtered_ext_basic_menu.item_changed.connect(
            self._modify_accepted_files_txt
        )
        self.filtered_ext_basic_display = QLineEdit(self)
        self.filtered_ext_basic_display.setReadOnly(True)
        filtered_ext_basic_widget = QWidget()
        filtered_ext_basic_layout = QHBoxLayout(filtered_ext_basic_widget)
        filtered_ext_basic_layout.setContentsMargins(0, 0, 0, 0)
        filtered_ext_basic_layout.addWidget(self.filtered_ext_basic_menu)
        filtered_ext_basic_layout.addWidget(self.filtered_ext_basic_display)

        self.form_layout = self._create_form_layout(
            filtered_ext_basic_lbl, filtered_ext_basic_widget
        )
        self.setLayout(self.form_layout)

    def update_items(self, items: Iterable[str]) -> None:
        """Updates the widget, accepts an iterable of extension strings"""
        self.filtered_ext_basic_menu.update_items(items)
        self._load_accepted_files_txt(items)

    def get_accepted_items(self) -> list[str]:
        """Returns a list of selected extensions"""
        return [x for x in self.filtered_ext_basic_display.text().split(", ")]

    def _load_accepted_files_txt(self, accepted_files: Iterable) -> None:
        files_list = [item for item, toggle in accepted_files if toggle]
        self.filtered_ext_basic_display.clear()
        self.filtered_ext_basic_display.setText(", ".join(files_list))

    @Slot(tuple)
    def _modify_accepted_files_txt(self, change: tuple[str, bool]) -> None:
        if self.filtered_ext_basic_display.text():
            files_list = self.filtered_ext_basic_display.text().split(", ")
        else:
            files_list = []

        ext, _ = change
        if ext in files_list:
            files_list.remove(ext)
        else:
            files_list.append(ext)

        self.filtered_ext_basic_display.clear()
        self.filtered_ext_basic_display.setText(", ".join(files_list))

    @staticmethod
    def _create_form_layout(widget1: QWidget, widget2: QWidget):
        form_layout = QFormLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.addWidget(widget1)
        form_layout.addWidget(widget2)
        return form_layout
