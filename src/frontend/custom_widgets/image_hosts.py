from collections.abc import Generator
from dataclasses import fields
from typing import Type

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QVBoxLayout, QWidget, QLabel

from src.config.config import Config
from src.enums.image_host import ImageHost
from src.payloads.image_hosts import ImagePayloadBase
from src.frontend.custom_widgets.masked_qline_edit import MaskedQLineEdit
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.resizable_stacked_widget import ResizableStackedWidget
from src.frontend.utils import clear_stacked_widget


class ImageHostConfig(QWidget):
    def __init__(self, data_class: Type[ImagePayloadBase], parent=None) -> None:
        super().__init__(parent)
        self.data_class = data_class
        self.inputs = {}
        self.main_layout = QVBoxLayout(self)

        for field_info in fields(data_class):
            label_text = field_info.name.replace("_", " ").title()
            input_field = MaskedQLineEdit(
                parent=self,
                masked=(field_info.name in ("password", "api_key")),
            )
            self.inputs[field_info.name] = input_field
            self.main_layout.addWidget(QLabel(label_text, self))
            self.main_layout.addWidget(input_field)

    def get_data(self):
        """Return a dataclass instance with values from the input fields."""
        data = {
            field: input_field.text().strip()
            for field, input_field in self.inputs.items()
        }
        return self.data_class(**data)

    def set_data(self, payload):
        """Set values of the input fields from a dataclass instance."""
        for field_info in fields(self.data_class):
            field_name = field_info.name
            if field_name in self.inputs:
                value = getattr(payload, field_name, None)
                self.inputs[field_name].setText(value)


class ImageHostStackedWidget(QWidget):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("imageHostStackedWidget")

        self.config = config
        self._stacked_widget_map = {}

        self.image_host_selector = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )
        self.image_host_selector.currentIndexChanged.connect(self._change_widget)

        self.stacked_widget = ResizableStackedWidget(self)
        self.stacked_widget.setContentsMargins(12, 0, 0, 0)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addWidget(self.image_host_selector)
        self.main_layout.addWidget(self.stacked_widget, stretch=1)

    def build_image_host_config_widgets(self) -> None:
        self.image_host_selector.clear()
        clear_stacked_widget(self.stacked_widget)

        for key, value in self.config.image_host_map.items():
            if value:
                image_widget = ImageHostConfig(data_class=type(value), parent=self)
                image_widget.set_data(value)
            else:
                image_widget = None
                self.stacked_widget.hide()

            self._stacked_widget_map[key] = image_widget
            self.stacked_widget.addWidget(
                image_widget if image_widget else QLabel("No configuration needed")
            )
            self.image_host_selector.addItem(str(key), userData=key.name)

        saved_idx = self.image_host_selector.findText(
            str(self.config.cfg_payload.image_host)
        )
        if saved_idx > -1:
            self.image_host_selector.setCurrentIndex(saved_idx)

    @Slot(int)
    def _change_widget(self, index: int) -> None:
        """Change the current widget in the stacked widget based on ComboBox selection"""
        self.stacked_widget.setCurrentIndex(index)
        current_data = self.image_host_selector.currentData()
        if not current_data:
            self.stacked_widget.hide()
            return

        if self.config.image_host_map[ImageHost(current_data)]:
            self.stacked_widget.show()
        else:
            self.stacked_widget.hide()

    def get_all_data(self) -> Generator[tuple[ImageHost, ImagePayloadBase], None, None]:
        """Generator to get data from the nested `ImageHost` widgets"""
        for key, value in self._stacked_widget_map.items():
            if value:
                yield key, value.get_data()

    def reset(self) -> None:
        """Reset data"""
        self.image_host_selector.setCurrentIndex(0)
