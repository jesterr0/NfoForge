from collections.abc import Sequence
from functools import partial
from pathlib import Path
from queue import Queue
from typing import Any, Type
import weakref

from PySide6.QtCore import QSize, QTimer, Qt, Slot
from PySide6.QtGui import QCursor, QIcon
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QFrame,
    QLayout,
    QStackedWidget,
    QWidget,
)

from src.backend.utils.working_dir import RUNTIME_DIR
from src.frontend.global_signals import GSigs
from src.plugins.plugin_prompt_dialog import PluginPromptDialog


def icon_button_factory(base_class):
    """Factory function to create an IconButton class inheriting from the specified base class."""

    class IconButton(base_class):
        def __init__(
            self,
            icon: str,
            object_name: str,
            width: int,
            height: int,
            text_included: bool = False,
            parent=None,
        ):
            """Initializes the IconButton object."""
            super().__init__(parent)

            self.icon = icon
            self.object_name = object_name
            self.icon_width = width
            self.icon_height = height
            self.text_included = text_included
            self.svg_path = Path(RUNTIME_DIR) / "svg" / self.icon

            self.setObjectName(self.object_name)

            # set up the button's initial properties
            self.setup_button()

            # connect to color scheme change signal
            self.app = QApplication.instance()
            self.app.styleHints().colorSchemeChanged.connect(self.update_icon)  # pyright: ignore [reportAttributeAccessIssue, reportOptionalMemberAccess]

            # set the initial icon based on the current color scheme
            self.update_icon(self.app.styleHints().colorScheme())  # pyright: ignore [reportAttributeAccessIssue, reportOptionalMemberAccess]

        def setup_button(self):
            """Sets up the button's initial properties."""
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            if self.text_included:
                self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        @Slot(Qt.ColorScheme)
        def update_icon(self, color_scheme: Qt.ColorScheme):
            """Updates the button icon based on the color scheme."""
            if color_scheme == Qt.ColorScheme.Dark:
                dark_icon_path = self.svg_path.parent / (
                    self.svg_path.stem + "_dark.svg"
                )
                # set the dark mode icon
                self.setIcon(QIcon(str(dark_icon_path)))
            else:
                # set the light mode icon
                self.setIcon(QIcon(str(self.svg_path)))
            self.setIconSize(QSize(self.icon_width, self.icon_height))

        def get_button(self):
            """Returns the button instance (self)."""
            return self

    return IconButton


def build_auto_theme_icon_buttons(
    widget,
    icon: str,
    object_name: str,
    width: int,
    height: int,
    text_included: bool = False,
    parent: QWidget | None = None,
) -> Any:
    """
    Builds and returns an IconButton instance that can swap SVG files based on the theme.

    This does require an included "*_dark.svg" version of each file that will use this.
    """
    IconButton = icon_button_factory(widget)
    icon_button = IconButton(
        icon=icon,
        object_name=object_name,
        width=width,
        height=height,
        text_included=text_included,
        parent=parent,
    )
    return icon_button.get_button()


class SvgWidget(QSvgWidget):
    def __init__(
        self,
        icon: str,
        icon_width: int,
        icon_height: int,
        parent=None,
    ):
        """Initializes the SvgWidget that updates based on color scheme changes."""
        super().__init__(parent)

        self.icon = icon
        self.icon_width = icon_width
        self.icon_height = icon_height
        self.svg_path = Path(RUNTIME_DIR) / "svg" / self.icon

        # connect to color scheme change signal
        self.app = QApplication.instance()
        self.app.styleHints().colorSchemeChanged.connect(self.update_icon)  # pyright: ignore [reportAttributeAccessIssue, reportOptionalMemberAccess]

        # set the initial icon based on the current color scheme
        self.update_icon(self.app.styleHints().colorScheme())  # pyright: ignore [reportAttributeAccessIssue, reportOptionalMemberAccess]

    @Slot(Qt.ColorScheme)
    def update_icon(self, color_scheme: Qt.ColorScheme):
        """Updates the SVG icon based on the color scheme."""
        if color_scheme == Qt.ColorScheme.Dark:
            dark_icon_path = self.svg_path.parent / (self.svg_path.stem + "_dark.svg")
            # load dark version of SVG
            self.load(str(dark_icon_path))
        else:
            # load light version of SVG
            self.load(str(self.svg_path))
        self.setFixedSize(QSize(self.icon_width, self.icon_height))


def build_auto_theme_svg_widget(icon: str, width: int, height: int, parent=None):
    """
    Builds and returns an SvgWidget instance that can swap SVG files based on the theme.

    This does require an included "*_dark.svg" version of each file that will use this.
    """
    svg_widget = SvgWidget(
        icon=icon, icon_width=width, icon_height=height, parent=parent
    )
    return svg_widget


def build_h_line(values: tuple[int, int, int, int]) -> QFrame:
    """
    Accepts a tuple of int to control the margins.

    (left, top, right, bottom)
    """
    h_line = QFrame()
    h_line.setFrameShape(QFrame.Shape.HLine)
    h_line.setFrameShadow(QFrame.Shadow.Sunken)
    h_line.setContentsMargins(*values)
    return h_line


def build_v_line(values: tuple[int, int, int, int]) -> QFrame:
    """
    Accepts a tuple of int to control the margins.

    (left, top, right, bottom)
    """
    h_line = QFrame()
    h_line.setFrameShape(QFrame.Shape.VLine)
    h_line.setFrameShadow(QFrame.Shadow.Sunken)
    h_line.setContentsMargins(*values)
    return h_line


def recursively_clear_layout(layout: QLayout) -> None:
    """Recursively clears layouts and deletes widgets as needed"""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()

        if widget is not None:
            widget.deleteLater()
        elif item.layout() is not None:
            recursively_clear_layout(item.layout())


def clear_stacked_widget(stacked_widget: QStackedWidget) -> None:
    """Recursively clears QStackedWidgets and deletes widgets as needed"""
    while stacked_widget.count():
        widget = stacked_widget.widget(0)
        stacked_widget.removeWidget(widget)
        widget.deleteLater()


def create_form_layout(
    widget1: QWidget,
    widget2: QWidget | None = None,
    margins: tuple[int, int, int, int] | None = None,
):
    """margins (tuple[int, int, int, int] | None, optional): Left, top, right, bottom"""
    form_layout = QFormLayout()
    if margins:
        form_layout.setContentsMargins(*margins)
    form_layout.addWidget(widget1)
    if widget2:
        form_layout.addWidget(widget2)
    return form_layout


class QWidgetTempStyle:
    """Singleton to temporarily manipulate stylesheets of widgets for warnings."""

    __slots__ = ("timers",)
    timers: "weakref.WeakKeyDictionary[QWidget, QTimer]"

    _instance = None

    def __new__(cls, *args, **kwargs) -> "QWidgetTempStyle":
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance.timers = weakref.WeakKeyDictionary()
        return cls._instance

    def set_temp_style(
        self,
        widget: QWidget,
        temp_style: str = "background-color: yellow;",
        duration: int = 1000,
        system_beep: bool = False,
    ) -> QTimer:
        """Temporarily set a widget's style, then restore the original after duration. Returns the timer for manual start."""
        if widget in self.timers:
            self.timers[widget].stop()

        if not hasattr(widget, "_original_style"):
            widget._original_style = widget.styleSheet()  # type: ignore
        widget.setStyleSheet(temp_style)
        timer = QTimer(singleShot=True, interval=duration)

        def restore():
            # only restore if the widget still exists and has the temp style
            if hasattr(widget, "_original_style"):
                widget.setStyleSheet(widget._original_style)  # type: ignore
                del widget._original_style  # type: ignore
            self.timers.pop(widget, None)

        timer.timeout.connect(restore)
        if system_beep:
            QApplication.beep()
        self.timers[widget] = timer
        return timer


def block_all_signals(widget: QWidget, block: bool) -> None:
    """Recursively block/unblock signals for parent and all child widgets."""

    def block_signals_recursive(w: QWidget) -> None:
        w.blockSignals(block)
        for child in w.findChildren(QWidget):
            block_signals_recursive(child)

    block_signals_recursive(widget)


def set_top_parent_geometry(widget: QWidget, delay: int = 1) -> None:
    """Find the topmost parent widget and set geometry for the given widget based on that."""

    def do_the_stuff(widget: QWidget) -> None:
        parent_widget = widget
        last_valid_parent = widget
        while True:
            next_parent = parent_widget.parentWidget()
            if next_parent is None:
                break
            last_valid_parent = next_parent
            parent_widget = next_parent

        if last_valid_parent:
            widget.setGeometry(last_valid_parent.geometry())

    QTimer.singleShot(delay, partial(do_the_stuff, widget))


def ask_thread_safe_prompt(title: str, prompt: str) -> tuple[bool, str]:
    """Uses a queue to wait for a message from where ever sent over QT signals

    Args:
        title (str): Title of prompt window.
        prompt (str): Prompt to ask user for input.

    Returns:
        tuple[bool, str]: bool = user pressed Ok, str = user input
    """
    q = Queue()
    GSigs().ask_prompt.emit(title, prompt, q)
    result = q.get()
    q.task_done()
    return result


def ask_thread_safe_multi_prompt(
    title: str, prompts: Sequence[str]
) -> tuple[bool, dict[str, str]]:
    """Uses a queue to wait for a message from where ever sent over QT signals

    Args:
        title (str): Title of prompt window.
        prompt (Sequence[str]): Prompts to ask user for input.

    Returns:
        tuple[bool, dict[str, str]]: bool = user pressed Ok, dict = user input with keys from the prompts.
    """
    q = Queue()
    GSigs().ask_multi_prompt.emit(title, prompts, q)
    result = q.get()
    q.task_done()
    return result


def ask_thread_safe_custom_prompt(widget: Type[PluginPromptDialog]) -> Any:
    """Uses a queue to wait for a message from where ever sent over QT signals

    Args:
        widget (PluginPromptDialog): Users custom PluginPromptDialog or QDialog (not instance).

    Widget should include a `results` instance variable, this can be what ever
    the user wants. By the time you close your PluginPromptDialog widget, it should have filled
    the `results` instance variable to pass back.

    ```python
    class UserDialog(PluginPromptDialog):
        def __init__(self, parent=None) -> None:
            super().__init__(parent=parent)
            self.setWindowTitle("User Custom Title")

            self.results = {"Blah", 123}
    ```

    Returns:
        Any: What ever the users widget returns from `results`.
    """
    q = Queue()
    GSigs().ask_custom_prompt.emit(widget, q)
    result = q.get()
    q.task_done()
    return result
