import traceback
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QMessageBox, QPushButton, QWizard

from src.config.config import ConfigManager
from src.context.factory import create_processing_context
from src.enums.media_type import MediaType
from src.enums.wizard import WizardPages
from src.frontend.global_signals import GSigs
from src.frontend.wizards.images import ImagesPage
from src.frontend.wizards.media_input import MediaInput
from src.frontend.wizards.media_search import MediaSearch
from src.frontend.wizards.nfo_template import NfoTemplate
from src.frontend.wizards.process import ProcessPage
from src.frontend.wizards.release_notes import ReleaseNotes
from src.frontend.wizards.rename_encode import RenameEncode
from src.frontend.wizards.rename_encode_series import RenameEncodeSeries
from src.frontend.wizards.series_match import SeriesMatch
from src.frontend.wizards.trackers import TrackersPage
from src.frontend.wizards.wizard_base_page import BaseWizardPage, DummyWizardPage
from src.logger.nfo_forge_logger import LOG

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class MainWindowWizard(QWizard):
    def __init__(
        self,
        config: ConfigManager,
        parent: "MainWindow",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MainWizard")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoCancelButton)

        self.config = config
        self.main_window = parent
        self.context = create_processing_context(
            self.config.settings,
            self.config.plugin_registry.plugins,
        )

        self._PAGES = self._generate_new_pages()
        self._START_PAGES = (
            WizardPages.INPUT_PAGE,
            WizardPages.PLUGIN_INPUT_PAGE,
        )

        self._insert_plugin_page()
        self._build_wizard_pages()
        self._set_start_page()

        self.next_button = QPushButton("Next", self)
        self.next_button.setToolTip("Save & Continue")
        self.next_button.setToolTipDuration(1500)
        self.setButton(QWizard.WizardButton.CommitButton, self.next_button)

        self.settings_button = QPushButton("Settings", self)
        self.settings_button.clicked.connect(GSigs().settings_clicked.emit)
        self.setButton(QWizard.WizardButton.CustomButton1, self.settings_button)

        self.reset_button = QPushButton("Start Over", self)
        self.reset_button.clicked.connect(self.reset_wizard)
        self.setButton(QWizard.WizardButton.CustomButton2, self.reset_button)
        self.setOption(QWizard.WizardOption.HaveCustomButton2)

        self.process_button = QPushButton("Process (Dupe Check)", self)
        self.process_button.clicked.connect(GSigs().wizard_process_btn_clicked.emit)
        GSigs().wizard_process_btn_change_txt.connect(self._change_process_button_text)
        GSigs().wizard_process_btn_set_hidden.connect(self.process_button.hide)
        self.setButton(QWizard.WizardButton.CustomButton3, self.process_button)
        self.setOption(QWizard.WizardOption.HaveCustomButton3)

        self.starting_buttons = (
            QWizard.WizardButton.CustomButton1,
            QWizard.WizardButton.Stretch,
            QWizard.WizardButton.CommitButton,
        )

        self.mid_flow_buttons = (
            QWizard.WizardButton.CustomButton2,
            QWizard.WizardButton.Stretch,
            QWizard.WizardButton.CommitButton,
        )

        self.ending_buttons = (
            QWizard.WizardButton.CustomButton2,
            QWizard.WizardButton.Stretch,
            QWizard.WizardButton.CustomButton3,
        )

        self.early_ending_buttons = (
            QWizard.WizardButton.CustomButton2,
            QWizard.WizardButton.Stretch,
        )

        self.setButtonLayout(self.starting_buttons)

        self._connect_current_id_changed()
        GSigs().wizard_set_disabled.connect(self._set_disabled)
        GSigs().wizard_next.connect(self.next)
        GSigs().wizard_next_button_change_txt.connect(self._change_next_button_text)
        GSigs().wizard_next_button_reset_txt.connect(self._reset_next_button_text)
        GSigs().wizard_end_early.connect(self.end_early)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # prevent enter/return key from pressing "Next" on the wizard
        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Escape):
            pass
        else:
            # call the base class implementation for other key events
            super().keyPressEvent(event)

    def nextId(self) -> int:
        """Control the flow between pages based on conditions"""
        current_page = WizardPages(self.currentId())
        return self._flow_production(current_page)

    @Slot(str)
    def _change_next_button_text(self, text: str) -> None:
        self.next_button.setText(text)

    @Slot()
    def _reset_next_button_text(self) -> None:
        self.next_button.setText("Next")

    @Slot(str)
    def _change_process_button_text(self, text: str) -> None:
        self.process_button.setText(text)

    @Slot()
    def reset_wizard(self) -> None:
        self.context = create_processing_context(
            self.config.settings,
            self.config.plugin_registry.plugins,
        )
        self.currentIdChanged.disconnect()
        self._remove_all_pages()
        self._PAGES = self._generate_new_pages()
        self._insert_plugin_page()
        self._build_wizard_pages()
        self._set_start_page()
        self._connect_current_id_changed()
        self._set_disabled(False)
        self.next_button.setText("Next")
        self.process_button.setText("Process (Dupe Check)")
        self.setButtonLayout(self.starting_buttons)
        self.restart()

    def _build_wizard_pages(self) -> None:
        for idx, page in enumerate(self._PAGES):
            self.setPage(idx + 1, page)

    def _set_start_page(self) -> None:
        if not self.config.settings.general.enable_plugins:
            self.setStartId(WizardPages.INPUT_PAGE.value)
            GSigs().main_window_update_status_bar_label.emit("Input")
        elif (
            self.config.settings.general.enable_plugins
            and self.config.settings.plugins.wizard_page
            and self.config.plugin_registry.plugins
        ):
            self.setStartId(WizardPages.PLUGIN_INPUT_PAGE.value)
            GSigs().main_window_update_status_bar_label.emit(
                self.config.settings.plugins.wizard_page
            )

    @Slot(int)
    def _handle_page_change(self, idx: int) -> None:
        if idx > -1 and WizardPages(idx) in self._START_PAGES:
            self.setButtonLayout(self.starting_buttons)
        else:
            if idx != WizardPages.PROCESS_PAGE.value:
                self.setButtonLayout(self.mid_flow_buttons)
            else:
                self.setButtonLayout(self.ending_buttons)

    @Slot(bool)
    def _set_disabled(self, value: bool) -> None:
        self.settings_button.setDisabled(value)
        self.next_button.setDisabled(value)
        self.reset_button.setDisabled(value)
        self.process_button.setDisabled(value)

    def end_early(self) -> None:
        self.setButtonLayout(self.early_ending_buttons)

    def _insert_plugin_page(self) -> None:
        if (
            self.config.settings.general.enable_plugins
            and self.config.settings.plugins.wizard_page
            and self.config.plugin_registry.plugins
        ):
            try:
                plugin_obj = self.config.plugin_registry.plugins[
                    self.config.settings.plugins.wizard_page
                ]
                if plugin_obj.wizard:
                    # insert the plugin wizard page into the correct spot
                    plugin_wizard = plugin_obj.wizard(
                        self.config, self.context, self.main_window
                    )
                    self._PAGES.pop(WizardPages.PLUGIN_INPUT_PAGE.value - 1)
                    self._PAGES.insert(
                        WizardPages.PLUGIN_INPUT_PAGE.value - 1, plugin_wizard
                    )
            except Exception as e:
                LOG.critical(LOG.LOG_SOURCE.FE, traceback.format_exc())
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to load plugin page:\n{e}\n\nPlugins are disabled until plugin issues are resolved.",
                )
                # revert to default media input page on failure
                self._PAGES.pop(WizardPages.PLUGIN_INPUT_PAGE.value - 1)
                self._PAGES.insert(
                    WizardPages.PLUGIN_INPUT_PAGE.value - 1,
                    MediaInput(self.config, self.context, self.main_window),
                )
                # disable plugins for the rest of the wizard flow
                self.config.settings.general.enable_plugins = False
                self.config.save()

    def _remove_all_pages(self) -> None:
        for page_id in reversed(self.pageIds()):
            page = self.page(page_id)
            self.removePage(page_id)
            # removePage() only detaches the page from the wizard -- it does
            # not delete the widget, so its GSigs connections (e.g. MediaSearch's
            # settings_close) stay alive. Schedule the old instance for
            # deletion so "Start Over" doesn't keep accumulating live, still
            # connected page objects each time fresh pages are built.
            if page is not None:
                page.deleteLater()

    def _connect_current_id_changed(self) -> None:
        self.currentIdChanged.connect(self._handle_page_change)

    def _flow_production(self, current_page: WizardPages) -> int:
        if current_page in self._START_PAGES:
            return WizardPages.MEDIA_SEARCH_PAGE.value

        elif current_page == WizardPages.MEDIA_SEARCH_PAGE:
            # if series navigate to the series matcher page
            if self.context.media_search.media_type is MediaType.SERIES:
                return WizardPages.SERIES_MATCHER_PAGE.value
            # movie
            else:
                if self.config.settings.movie.enabled:
                    return WizardPages.RENAME_ENCODE_MOVIES_PAGE.value
                elif (
                    not self.config.settings.movie.enabled
                    and self.config.settings.screenshots.enabled
                ):
                    return WizardPages.IMAGES_PAGE.value
                return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.SERIES_MATCHER_PAGE:
            if self.config.settings.series.enabled:
                return WizardPages.RENAME_ENCODE_SERIES_PAGE.value
            elif self.config.settings.screenshots.enabled:
                return WizardPages.IMAGES_PAGE.value
            return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.RENAME_ENCODE_MOVIES_PAGE:
            if self.config.settings.screenshots.enabled:
                return WizardPages.IMAGES_PAGE.value
            else:
                return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.RENAME_ENCODE_SERIES_PAGE:
            if self.config.settings.screenshots.enabled:
                return WizardPages.IMAGES_PAGE.value
            else:
                return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.IMAGES_PAGE:
            return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.TRACKERS_PAGE:
            return WizardPages.RELEASE_NOTES_PAGE.value

        elif current_page == WizardPages.RELEASE_NOTES_PAGE:
            return WizardPages.NFO_TEMPLATE_PAGE.value

        elif current_page == WizardPages.NFO_TEMPLATE_PAGE:
            return WizardPages.PROCESS_PAGE.value

        elif current_page == WizardPages.PROCESS_PAGE:
            return -1

        return -1

    def _generate_new_pages(self) -> list[BaseWizardPage]:
        """Helper method to generate wizard page instances and return them."""
        pages = (
            MediaInput,
            DummyWizardPage,
            MediaSearch,
            SeriesMatch,
            RenameEncode,
            RenameEncodeSeries,
            ImagesPage,
            TrackersPage,
            ReleaseNotes,
            NfoTemplate,
            ProcessPage,
        )
        return [p(self.config, self.context, self.main_window) for p in pages]
