from collections.abc import Iterable
from pathlib import Path
from typing import Any, TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QWizardPage,
)

from src.backend.utils.file_utilities import find_largest_file_in_directory
from src.backend.utils.file_utilities import generate_unique_date_name
from src.config.config import Config
from src.frontend.custom_widgets.dnd_factory import DNDButton, DNDToolButton

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class BaseWizardPage(QWizardPage):
    REQUIRED_CHILD_METHODS = ("reset_page",)

    def __init__(self, config: Config, parent: "MainWindow | Any") -> None:
        super().__init__(parent)
        self._custom_abstract_method_check()
        self.config = config

    def _custom_abstract_method_check(self) -> None:
        """This is a work around to avoid mixin with ABC"""
        for method in self.REQUIRED_CHILD_METHODS:
            if not callable(getattr(self, method, None)):
                raise NotImplementedError(
                    f"You must implement the {method} method for {self.__class__.__name__}"
                )

    def validatePage(self) -> bool:
        """
        Overrides QWizardPage validatePage and should ALWAYS be called in children pages before
        returning True.
        """
        if not self.config.media_input_payload.working_dir:
            raise FileNotFoundError(
                "Could not detect working directory that should be set from child wizard input "
                "page using method set_working_dir"
            )
        return True

    def set_working_dir(self, path: Path) -> None:
        """Convenient method to set the working directory for MediaInputPayload"""
        self.config.media_input_payload.working_dir = path

    def gen_unique_date_name(self, path: Path) -> str:
        """Convenient method to generate unique date name for working directory for MediaInputPayload"""
        return generate_unique_date_name(path.stem)

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
