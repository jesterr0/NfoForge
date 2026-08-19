from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QWidget,
    QWizardPage,
)

from src.backend.utils.file_utilities import (
    find_largest_file_in_directory,
    generate_unique_date_name,
)
from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.frontend.custom_widgets.dnd_factory import DNDButton, DNDToolButton

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class BaseWizardPage(QWizardPage):
    # REQUIRED_CHILD_METHODS = ("reset_page",)

    def __init__(
        self,
        config: ConfigManager,
        context: ProcessingContext,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        # self._custom_abstract_method_check()
        self.config = config
        self.context = context

    # def _custom_abstract_method_check(self) -> None:
    #     """This is a work around to avoid mixin with ABC"""
    #     for method in self.REQUIRED_CHILD_METHODS:
    #         if not callable(getattr(self, method, None)):
    #             raise NotImplementedError(
    #                 f"You must implement the {method} method for {self.__class__.__name__}"
    #             )

    def teardown(self) -> None:
        """Release anything of this page's that outlives the page.

        Called by `MainWindowWizard._remove_all_pages` as the wizard is rebuilt
        -- by Start Over and by resuming a job -- before the page is scheduled
        for deletion. A no-op unless a page has something to hand back.

        The case this exists for is a subscription to the global signal bus. A
        removed page keeps answering `GSigs()` until it is really destroyed,
        and `deleteLater()` only *schedules* that: which event loop runs it,
        and when, is not something the rebuild waits for. Anything whose
        correctness depends on only the live page reacting has to be given up
        here rather than left to that timing.
        """

    def validatePage(self) -> bool:
        """
        Overrides QWizardPage validatePage and should ALWAYS be called in children pages before
        returning True.
        """
        if not self.context.media_input.working_dir:
            raise FileNotFoundError(
                "Could not detect working directory that should be set from child wizard input "
                "page using method set_working_dir"
            )
        return True

    def set_working_dir(self, path: Path) -> None:
        """Convenient method to set the working directory for MediaInputPayload"""
        self.context.media_input.working_dir = path

    def gen_unique_date_name(self, path: Path) -> str:
        """Convenient method to generate unique date name for working directory for MediaInputPayload"""
        return generate_unique_date_name(path.stem)

    @staticmethod
    def find_largest_media(directory: Path, extensions: Iterable[str]) -> Path | None:
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

    def __init__(
        self, config: ConfigManager, context: ProcessingContext, parent: "MainWindow"
    ) -> None:
        super().__init__(config, context, parent)
