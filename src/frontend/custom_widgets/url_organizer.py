import re

from PySide6.QtWidgets import (
    QMessageBox,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QCheckBox,
    QLineEdit,
    QLayout,
    QWidget,
)
from PySide6.QtCore import Slot, Signal, Qt, QTimer
from PySide6.QtGui import QTextOption, QWheelEvent

from src.exceptions import ImageUploadError
from src.enums.url_type import URLType
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.basic_code_editor import CodeEditor
from src.packages.custom_types import ImageUploadData


class URLOrganizer(QWidget):
    settings_changed = Signal()

    def __init__(
        self,
        demo_mode: bool = False,
        remove_margins: bool = False,
        alt_text: str = "",
        columns: int = 1,
        vertical: int = 1,
        horizontal: int = 1,
        image_urls: dict[int, ImageUploadData] | None = None,
        url_mode: int = 0,
        url_type: URLType = URLType.BBCODE,
        image_width: int = 0,
        manual_control: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.alt_text = alt_text
        self.current_columns = columns
        self.current_vertical = vertical
        self.current_horizontal = horizontal
        self.image_urls = image_urls
        self.url_mode = url_mode
        self.url_type = url_type
        self.image_width = image_width
        self.manual_control = manual_control

        column_layout, self.column_spin_box = self._build_spinbox(
            "Columns", 1, 2, self.current_columns
        )
        self.column_spin_box.valueChanged.connect(self._trigger_update)

        vertical_space_layout, self.vertical_space_spin_box = self._build_spinbox(
            "Vertical Spacing", 1, 10, self.current_vertical
        )
        self.vertical_space_spin_box.valueChanged.connect(self._trigger_update)

        horizontal_space_layout, self.horizontal_space_spin_box = self._build_spinbox(
            "Horizontal Spacing", 1, 10, self.current_horizontal
        )
        self.horizontal_space_spin_box.valueChanged.connect(self._trigger_update)

        self.width_spinbox_changed = None
        self.width_spinbox = QSpinBox()
        self.width_spinbox.wheelEvent = self._ignore_wheel_event
        self.width_spinbox.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.width_spinbox.setRange(0, 8000)
        self.width_spinbox.setValue(self.image_width)
        self.width_spinbox.editingFinished.connect(self._update_width)

        self.image_alt = QLineEdit()
        self.image_alt.setText(self.alt_text)
        self.image_alt.editingFinished.connect(self._update_width)

        self.url_type_selection = CustomComboBox(
            completer=True, disable_mouse_wheel=True
        )
        for url_type_item in URLType:
            self.url_type_selection.addItem(str(url_type_item), url_type_item.name)
        url_current_index = self.url_type_selection.findText(str(self.url_type))
        if url_current_index >= 0:
            self.url_type_selection.setCurrentIndex(url_current_index)
        self.url_type_selection.currentIndexChanged.connect(self._trigger_update)

        self.linked_toggle = QCheckBox("Linked")
        self.linked_toggle.setToolTip(
            "Will add clickable tags with full URLs if available"
        )
        self.linked_toggle.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.linked_toggle.setChecked(bool(self.url_mode))
        self.linked_toggle.clicked.connect(self._trigger_update)

        self.manual_toggle = QCheckBox("Manual")
        self.manual_toggle.setToolTip(
            "Gives the user manual control (disables all UI controls)"
        )
        self.manual_toggle.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.manual_toggle.clicked.connect(self._manual_toggle)
        self.manual_toggle.setChecked(bool(self.manual_control))
        QTimer.singleShot(1, lambda: self._manual_toggle(bool(self.manual_control)))

        self._disable_widgets_on_manual = (
            self.column_spin_box,
            self.vertical_space_spin_box,
            self.horizontal_space_spin_box,
            self.url_type_selection,
            self.width_spinbox,
            self.image_alt,
            self.linked_toggle,
        )

        bbcode_button_layout = QHBoxLayout()
        bbcode_button_layout.addWidget(QLabel("URL Type"))
        bbcode_button_layout.addWidget(self.url_type_selection)
        bbcode_button_layout.addWidget(QLabel("Image Width"))
        bbcode_button_layout.addWidget(self.width_spinbox)
        bbcode_button_layout.addWidget(QLabel("Image Alt"))
        bbcode_button_layout.addWidget(self.image_alt)
        bbcode_button_layout.addWidget(self.linked_toggle)
        bbcode_button_layout.addWidget(self.manual_toggle)

        self.text_area = CodeEditor(
            line_numbers=True, wrap_text=False, mono_font=True, parent=self
        )
        self.text_area.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        self._load_urls(demo_mode)
        self.text_area.textChanged.connect(self._text_area_changed)

        top_layout = QHBoxLayout()
        top_layout.addLayout(column_layout)
        top_layout.addLayout(vertical_space_layout)
        top_layout.addLayout(horizontal_space_layout)

        layout = QVBoxLayout(self)
        if remove_margins:
            layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top_layout)
        layout.addLayout(bbcode_button_layout)
        layout.addWidget(self.text_area)

    def get_urls(self) -> str | None:
        urls = self.text_area.toPlainText()
        return urls if urls else None

    def load_data(self, data: dict[int, ImageUploadData]) -> None:
        self.manual_control = False
        self.manual_toggle.setChecked(False)
        self._disable_widgets(False)
        self.image_urls = data
        self._update_text()

    @Slot()
    def _update_width(self) -> None:
        """Prevents double event fires for using the spinbox with the keyboard"""
        if not self.width_spinbox_changed:
            self.width_spinbox_changed = True
            self._update_text()
            self.width_spinbox_changed = None

    @Slot(int)
    def _trigger_update(self, e: int | None = None) -> None:
        self._update_text(e)
        self.settings_changed.emit()

    @Slot(bool)
    def _manual_toggle(self, toggle: bool) -> None:
        self.manual_control = toggle
        if toggle is False:
            self._update_text()

        self._disable_widgets(toggle)

    def _disable_widgets(self, toggle: bool) -> None:
        for widget in self._disable_widgets_on_manual:
            widget.setDisabled(toggle)

    @Slot(int)
    def _update_text(self, _: int | None = None) -> None:
        """Updates the text area with formatted URLs based on current settings."""
        if self.manual_control:
            return

        self._toggle_controls(False)

        self.alt_text = self.image_alt.text()
        self.current_columns = self.column_spin_box.value()
        self.current_vertical = self.vertical_space_spin_box.value()
        self.current_horizontal = self.horizontal_space_spin_box.value()
        self.url_mode = int(self.linked_toggle.isChecked())
        self.url_type = URLType(self.url_type_selection.currentData())
        self.image_width = self.width_spinbox.value()

        new_text = self._generate_formatted_text()
        new_text = self._apply_spacing(new_text)

        self.text_area.blockSignals(True)
        self.text_area.clear()
        self.text_area.setPlainText(new_text)
        self.text_area.blockSignals(False)

        self._toggle_controls(True)

    def _generate_formatted_text(self) -> str:
        """Generates formatted text based on the current settings."""
        image_upload_failures = 0
        new_text = ""

        if self.image_urls:
            for idx, (url, med_url) in self.image_urls.items():
                if not url and not med_url:
                    image_upload_failures += 1
                    continue

                if url:
                    formatted_url = self._format_url(url, med_url)
                    if self.current_columns == 1:
                        new_text += formatted_url + "\n"
                    elif self.current_columns == 2:
                        new_text += self._format_columns(idx, formatted_url)

            if image_upload_failures > 0:
                QMessageBox.warning(
                    self,
                    "Upload Error",
                    f"Failure to upload {image_upload_failures} image(s)",
                )

        return new_text

    def _format_url(self, url: str, med_url: str | None) -> str:
        """Formats a single URL based on the current URL mode."""
        if self.url_type == URLType.BBCODE:
            return self._bbcode_url(url, med_url)
        elif self.url_type == URLType.HTML:
            return self._html_url(url, med_url)
        else:
            raise ImageUploadError("Failed to format urls")

    def _bbcode_url(self, url: str, med_url: str | None) -> str:
        current_width = (
            f"={self.image_width}"
            if (self.image_width and self.image_width != 0)
            else ""
        )

        alt_txt = self._alt_text()

        if self.url_mode == 0 and med_url:
            return f"[img{current_width}{alt_txt}]{med_url}[/img]"

        elif self.url_mode == 1 and med_url:
            return f"[url={url}][img{current_width}{alt_txt}]{med_url}[/img][/url]"

        return f"[img{current_width}{alt_txt}]{url}[/img]"

    def _html_url(self, url: str, med_url: str | None) -> str:
        current_width = (
            f'width="{self.image_width}" '
            if (self.image_width and self.image_width != 0)
            else ""
        )

        alt_txt = self._alt_text()

        if self.url_mode == 0 and med_url:
            return f'<img {current_width}src="{med_url}"{alt_txt}>'

        elif self.url_mode == 1 and med_url:
            return f'<a href="{url}"><img {current_width}src="{med_url}"{alt_txt}></a>'

        return f'<img {current_width}src="{url}"{alt_txt}>'

    def _alt_text(self) -> str:
        return f' alt="{self.alt_text}"' if self.alt_text else ""

    def _format_columns(self, idx: int, formatted_url: str) -> str:
        """Formats the URLs for column layout."""
        if (idx + 1) % 2 == 0:
            return f" {formatted_url}\n"
        return formatted_url

    def _apply_spacing(self, text: str) -> str:
        """Applies vertical and horizontal spacing to the formatted text."""
        text = re.sub(r"\n+", "\n" * self.current_vertical, text, flags=re.MULTILINE)
        text = re.sub(
            r"(?<=>|\])[ ]+(?=<|\[)",
            " " * self.current_horizontal,
            text,
            flags=re.MULTILINE,
        )
        return text

    def _load_urls(self, demo_mode: bool = False) -> None:
        if self.image_urls:
            self._update_text()
            return

        if demo_mode:
            self.image_urls = {}
            for i in range(6):
                if i == 3:
                    self.image_urls[i] = ImageUploadData(f"long_url_{i}", None)
                    continue
                self.image_urls[i] = ImageUploadData(
                    f"long_url_{i}", f"med_url_{i}.png"
                )
            self._update_text()

    def _text_area_changed(self) -> None:
        self.manual_toggle.setChecked(True)
        self.manual_control = True
        self._disable_widgets(True)

    def _toggle_controls(self, toggle: bool) -> None:
        self.column_spin_box.setEnabled(toggle)
        self.vertical_space_spin_box.setEnabled(toggle)
        self.horizontal_space_spin_box.setEnabled(toggle)

    def _build_spinbox(
        self, lbl_str: str, minimum: int, maximum: int, cur_value: int | None = None
    ) -> tuple[QLayout, QSpinBox]:
        spinbox = QSpinBox(self)
        spinbox.setRange(minimum, maximum)
        spinbox.wheelEvent = self._ignore_wheel_event
        spinbox.lineEdit().setReadOnly(True)
        if cur_value:
            spinbox.setValue(cur_value)
        layout = QVBoxLayout()
        layout.addWidget(QLabel(lbl_str, self))
        layout.addWidget(spinbox)
        return layout, spinbox

    def reset(self) -> None:
        self.image_urls = None
        self.text_area.clear()

    @staticmethod
    def _ignore_wheel_event(event: QWheelEvent) -> None:
        event.ignore()
