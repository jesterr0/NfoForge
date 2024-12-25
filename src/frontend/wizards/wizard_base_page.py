from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QWizardPage,
    QToolButton,
    QPushButton,
)

from src.backend.utils.file_utilities import find_largest_file_in_directory
from src.config.config import Config
from src.frontend.custom_widgets.dnd_factory import DNDButton, DNDToolButton

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class BaseWizardPage(QWizardPage):
    REQUIRED_CHILD_METHODS = ("reset_page",)

    def __init__(self, config: Config, parent: "MainWindow | Any") -> None:
        super().__init__(parent)
        self._custom_abstract_method_check()

    def _custom_abstract_method_check(self) -> None:
        """This is a work around to avoid mixin with ABC"""
        for method in self.REQUIRED_CHILD_METHODS:
            if not callable(getattr(self, method, None)):
                raise NotImplementedError(
                    f"You must implement the {method} method for {self.__class__.__name__}"
                )

    @staticmethod
    def find_largest_media(directory: Path, extensions: Iterable) -> Path | None:
        return find_largest_file_in_directory(directory, extensions, False)

    @staticmethod
    def _button_form_layout(
        label: QLabel,
        entry: QLineEdit,
        button: DNDToolButton | QToolButton | DNDButton | QPushButton,
        button2: DNDToolButton | QToolButton | DNDButton | QPushButton | None = None,
    ) -> QHBoxLayout:
        form_layout = QFormLayout()
        form_layout.addWidget(label)
        form_layout.addWidget(entry)
        source_layout = QHBoxLayout()
        source_layout.addLayout(form_layout)
        source_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignBottom)
        if button2:
            source_layout.addWidget(button2, 0, Qt.AlignmentFlag.AlignBottom)
        return source_layout


class DummyWizardPage(BaseWizardPage):
    """Dummy Wizard Page to hold the plugin page spot as needed"""

    def __init__(self, config: Config, parent: "MainWindow") -> None:
        super().__init__(config, parent)

    def reset_page(self) -> None:
        pass
