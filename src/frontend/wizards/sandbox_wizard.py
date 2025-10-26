from pathlib import Path

from guessit import guessit
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from src.config.config import Config
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.frontend.custom_widgets.series_episode_mapper import SeriesEpisodeMapper
from src.frontend.global_signals import GSigs
from src.frontend.utils import set_top_parent_geometry
from src.frontend.wizards.media_input import MediaInput
from src.frontend.wizards.media_search import MediaSearch


class SandboxMediaInputPage(QWizardPage):
    """Wrapper page for MediaInput in sandbox mode"""

    def __init__(self, config: Config, context: ProcessingContext, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Sandbox Input")
        self.setSubTitle("Select your media file or directory")
        self.setCommitPage(True)

        self.config = config
        self.context = context

        self.media_input = MediaInput(
            config, context, parent, on_finished_cb=self._on_validation_finished
        )

        self.setLayout(self.media_input.main_layout)

    def _on_validation_finished(self) -> None:
        """Called when async validation is complete, proceed to next page"""
        if self.wizard():
            self.wizard().next()

    def validatePage(self) -> bool:
        """Validate the media input"""
        return self.media_input.validatePage()


class SandboxMediaSearchPage(QWizardPage):
    """Wrapper page for MediaSearch in sandbox mode"""

    def __init__(self, config: Config, context: ProcessingContext, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Sandbox Search")
        self.setSubTitle("Search and select your media")
        self.setCommitPage(True)

        self.config = config
        self.context = context

        self.media_search = MediaSearch(
            config, context, parent, on_finished_cb=self._on_validation_finished
        )

        self.setLayout(self.media_search.main_layout)

    def _on_validation_finished(self) -> None:
        """Called when async validation is complete, proceed to next page"""
        if self.wizard():
            # check if this should be the final page
            # this is the final page, accept/finish the wizard
            if self.wizard().nextId() == -1:
                self.wizard().accept()
            # go to the next page
            else:
                self.wizard().next()

    def validatePage(self) -> bool:
        """Validate the media search"""
        return self.media_search.validatePage()

    def initializePage(self) -> None:
        """Initialize the page when it becomes current"""
        super().initializePage()
        # auto-populate search based on input file
        if self.context.media_input.input_path:
            file_path = self.context.media_input.input_path
            guess = guessit(Path(file_path).name)
            guessed_title = guess.get("title", "")
            year = guess.get("year", "")
            if year:
                guessed_title = f"{guessed_title} {year}"

            self.media_search.search_entry.setText(guessed_title)
            self.media_search._search_tmdb_api()


class SandboxSeriesMapperPage(QWizardPage):
    """Page for series episode mapping"""

    def __init__(self, config: Config, context: ProcessingContext, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Sandbox Series Mapping")
        self.setSubTitle("Map your files to episodes")
        self.setCommitPage(True)

        self.config = config
        self.context = context

        self.series_mapper = SeriesEpisodeMapper(self)

        self.setLayout(self.series_mapper.main_layout)

    def validatePage(self) -> bool:
        """Validate the series mapping"""
        if not self.series_mapper.is_valid():
            QMessageBox.warning(
                self,
                "Incomplete Mapping",
                "Please ensure all files are properly mapped to episodes before continuing.",
            )
            return False

        # store the episode mappings in config
        self.context.media_input.series_episode_map = (
            self.series_mapper.get_episode_map()
        )
        return True

    def initializePage(self) -> None:
        """Initialize the page when it becomes current"""
        super().initializePage()
        # load data when page is shown
        if self.context.media_input and self.context.media_search:
            self.series_mapper.load_data(
                self.context.media_input,
                self.context.media_search,
            )


class SandboxWizard(QWizard):
    """Wizard for sandbox input flow"""

    # pages
    PAGE_INPUT = 0
    PAGE_SEARCH = 1
    PAGE_SERIES_MAPPER = 2

    def __init__(self, config: Config, context: ProcessingContext, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sandbox Input")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoCancelButton)

        self.config = config
        self.context = context

        # modify default buttons
        self.next_button = QPushButton("Accept", self)
        self.next_button.setToolTip("Save & Continue")
        self.next_button.setToolTipDuration(1500)
        self.setButton(QWizard.WizardButton.CommitButton, self.next_button)
        self.setButtonText(QWizard.WizardButton.FinishButton, "Accept")
        self.setButtonLayout(
            (
                QWizard.WizardButton.Stretch,
                QWizard.WizardButton.CommitButton,
                QWizard.WizardButton.FinishButton,
            )
        )

        # create pages
        self.input_page = SandboxMediaInputPage(config, context, self)
        self.search_page = SandboxMediaSearchPage(config, context, self)
        self.series_mapper_page = SandboxSeriesMapperPage(config, context, self)

        # add pages
        self.setPage(self.PAGE_INPUT, self.input_page)
        self.setPage(self.PAGE_SEARCH, self.search_page)
        self.setPage(self.PAGE_SERIES_MAPPER, self.series_mapper_page)

    def nextId(self) -> int:
        """Determine the next page based on current page and content"""
        current_id = self.currentId()

        if current_id == self.PAGE_INPUT:
            return self.PAGE_SEARCH
        elif current_id == self.PAGE_SEARCH:
            # check if selected media is a series
            current_item = self.search_page.media_search.listbox.currentItem()
            if current_item:
                item_key = current_item.text()
                item_data = self.search_page.media_search.backend.media_data.get(
                    item_key
                )
                if (
                    item_data
                    and MediaType.search_type(item_data.get("media_type"))
                    is MediaType.SERIES
                ):
                    return self.PAGE_SERIES_MAPPER
                else:
                    # not a series, skip to finish
                    return -1
            else:
                # no selection yet, default to series mapper to keep "Next" button
                # this will be re-evaluated when user makes a selection
                return self.PAGE_SERIES_MAPPER
        elif current_id == self.PAGE_SERIES_MAPPER:
            return -1

        return -1


class SandboxMainWindow(QMainWindow):
    """Main window for sandbox input with built-in status bar to mimic NfoForge's main window"""

    def __init__(self, config: Config, context: ProcessingContext, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowTitle("Sandbox Input")

        set_top_parent_geometry(self)

        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Ready")
        GSigs().main_window_update_status_tip.connect(self._update_status_bar)
        GSigs().main_window_clear_status_tip.connect(self._clear_status_bar)

        self.wizard = SandboxWizard(config, context, self)
        self.wizard.accepted.connect(self.accept)
        self.wizard.rejected.connect(self.reject)

        # store result for exec()
        self._result = QDialog.DialogCode.Rejected

        # create a widget to be the main widget to embed the wizard into
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        central_widget_layout = QVBoxLayout(central_widget)
        central_widget_layout.setContentsMargins(0, 0, 0, 0)
        central_widget_layout.addWidget(self.wizard, stretch=1)

    def accept(self) -> None:
        """Accept the dialog"""
        self._result = QDialog.DialogCode.Accepted
        self.close()

    def reject(self) -> None:
        """Reject the dialog"""
        self._result = QDialog.DialogCode.Rejected
        self.close()

    @Slot(str, int)
    def _update_status_bar(self, msg: str, _timer: int) -> None:
        """Update the status bar with a message"""
        self.status_bar.showMessage(msg)

    @Slot()
    def _clear_status_bar(self) -> None:
        """Clear the status bar"""
        self.status_bar.clearMessage()

    def exec(self) -> int:
        """Show the window modally and return the result"""
        self.show()
        # process events until the window is closed
        while self.isVisible():
            QApplication.processEvents()
        return self._result
