from enum import Enum
from typing import TYPE_CHECKING, Type

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLayout,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.config.config import Config
from src.frontend.custom_widgets.combo_box import CustomComboBox

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow
    from src.frontend.stacked_windows.settings.settings import Settings


class BaseSettings(QWidget):
    """
    Inherited in all other settings pages. We'll keep common
    methods etc. in this class.
    """

    load_saved_settings = Signal()
    update_saved_settings = Signal()
    updated_settings_applied = Signal()

    REQUIRED_CHILD_METHODS = ("apply_defaults",)

    def __init__(
        self, config: Config, main_window: "MainWindow", parent: "Settings"
    ) -> None:
        super().__init__(parent)
        self._custom_abstract_method_check()

        self.config = config
        self.main_window = main_window
        self.settings_window = parent

        # this timer is to be used in the child classes, not to be included in
        # this base templates layout
        self._reset_settings_timer = QTimer()
        self._reset_settings_timer.timeout.connect(self._reset_settings_button)
        self._reset_settings_btn = QToolButton()
        self._reset_settings_btn.setText("Reset")
        self._reset_settings_btn.setToolTip("Reset settings to default")
        self._reset_settings_btn.clicked.connect(self._reset_settings_click)
        self.reset_layout = QHBoxLayout()
        self.reset_layout.setContentsMargins(6, 12, 6, 6)
        self.reset_layout.addWidget(
            self._reset_settings_btn, stretch=1, alignment=Qt.AlignmentFlag.AlignRight
        )
        self.reset_layout.addStretch()

        scroll_area = QScrollArea(self)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidgetResizable(True)
        inner_widget = QWidget(scroll_area)
        scroll_area.setWidget(inner_widget)
        self.inner_layout = QVBoxLayout(inner_widget)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 2)
        layout.addWidget(scroll_area)

    def _custom_abstract_method_check(self) -> None:
        """This is a work around to avoid mixin with ABC"""
        for method in self.REQUIRED_CHILD_METHODS:
            if not callable(getattr(self, method, None)):
                raise NotImplementedError(
                    f"You must implement the {method} method for {self.__class__.__name__}"
                )

    def add_widget(self, widget: QWidget, add_stretch: bool = False, **kwargs) -> None:
        """Adds widget to parent layout, removing and adding the spacer item to the bottom

        add_stretch should be applied to the last item added to the layout"""
        self.inner_layout.addWidget(widget, **kwargs)
        if add_stretch:
            self.inner_layout.addStretch()

    def add_layout(self, layout: QLayout, add_stretch: bool = False, **kwargs) -> None:
        """Adds layout to parent layout

        add_stretch should be applied to the last item added to the layout"""
        self.inner_layout.addLayout(layout, **kwargs)
        if add_stretch:
            self.inner_layout.addStretch()

    def _reset_settings_button(self) -> None:
        """Stops the timer and sets the text back to it's default state"""
        self._reset_settings_timer.stop()
        self._reset_settings_btn.setText("Reset")

    def _reset_settings_click(self) -> None:
        """
        Calls `_reset_settings_button` if the timer is active,
        otherwise it starts the timer and calls the children
        method `apply_defaults`
        """
        if self._reset_settings_timer.isActive():
            self._reset_settings_button()
            self.apply_defaults()
        else:
            self._reset_settings_btn.setText("Confirm?")
            self._reset_settings_timer.start(3000)

    def apply_defaults(self) -> None:
        raise NotImplementedError(
            "You must implement method 'apply_defaults' in children classes"
        )

    @staticmethod
    def load_combo_box(
        widget: CustomComboBox, enum: Type[Enum], saved_data: Enum
    ) -> None:
        """Clears CustomComboBox and reloads it with fresh data, setting the default value if available"""
        widget.clear()
        for item in enum:
            widget.addItem(str(item), item)
        current_index = widget.findText(str(enum(saved_data)))
        if current_index >= 0:
            widget.setCurrentIndex(current_index)
