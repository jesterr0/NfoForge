from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWizard, QPushButton
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QKeyEvent

from src.config.config import Config
from src.enums.wizard import WizardPages
from src.enums.profile import Profile
from src.frontend.wizards.wizard_base_page import DummyWizardPage
from src.frontend.wizards.media_input_basic import MediaInputBasic
from src.frontend.wizards.media_input_advanced import MediaInputAdvanced
from src.frontend.wizards.media_search import MediaSearch
from src.frontend.wizards.rename_encode import RenameEncode
from src.frontend.wizards.images import ImagesPage
from src.frontend.wizards.nfo_template import NfoTemplate
from src.frontend.wizards.trackers import TrackersPage
from src.frontend.wizards.overview import Overview
from src.frontend.wizards.process import ProcessPage


if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class MainWindowWizard(QWizard):
    set_disabled = Signal(bool)

    def __init__(
        self,
        config: Config,
        parent: "MainWindow",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MainWizard")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoCancelButton)

        self.config = config
        self.main_window = parent

        self._PAGES = [
            MediaInputBasic(self.config, self.main_window),
            MediaInputAdvanced(self.config, self.main_window),
            DummyWizardPage(self.config, self.main_window),
            MediaSearch(self.config, self.main_window),
            RenameEncode(self.config, self.main_window),
            ImagesPage(self.config, self.main_window),
            TrackersPage(self.config, self.main_window),
            NfoTemplate(self.config, self.main_window),
            Overview(self.config, self.main_window),
            ProcessPage(self.config, self.main_window),
        ]

        self._START_PAGES = (
            WizardPages.BASIC_INPUT_PAGE,
            WizardPages.ADVANCED_INPUT_PAGE,
            WizardPages.PLUGIN_INPUT_PAGE,
        )

        self._insert_plugin_page()
        self._build_wizard_pages()
        self._set_start_page()

        self.next_button = QPushButton("Next")
        self.next_button.setToolTip("Save & Continue")
        self.next_button.setToolTipDuration(1500)
        self.setButton(QWizard.WizardButton.CommitButton, self.next_button)

        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.main_window.settings_clicked.emit)
        self.setButton(QWizard.WizardButton.CustomButton1, self.settings_button)

        self.reset_button = QPushButton("Start Over")
        self.reset_button.clicked.connect(self.reset_wizard)
        self.setButton(QWizard.WizardButton.CustomButton2, self.reset_button)
        self.setOption(QWizard.WizardOption.HaveCustomButton2)

        self.process_button = QPushButton("Process (Dupe Check)")
        self.process_button.clicked.connect(self.main_window.wizard_process_btn_clicked)
        self.main_window.wizard_process_btn_change_txt.connect(
            self._change_process_button_text
        )
        self.main_window.wizard_process_btn_set_hidden.connect(self.process_button.hide)
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

        self.setButtonLayout(self.starting_buttons)

        self._connect_current_id_changed()
        self.set_disabled.connect(self._set_disabled)

    def keyPressEvent(self, event: QKeyEvent):  # pyright: ignore [reportIncompatibleMethodOverride]
        # prevent enter/return key from pressing "Next" on the wizard
        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Escape):
            pass
        else:
            # Call the base class implementation for other key events
            super().keyPressEvent(event)

    def nextId(self) -> int:
        """Control the flow between pages based on conditions"""
        current_page = WizardPages(self.currentId())
        if self.config.DEV_MODE:
            return self._flow_dev(current_page)
        else:
            return self._flow_production(current_page)

    @Slot(str)
    def _change_process_button_text(self, text: str) -> None:
        self.process_button.setText(text)

    @Slot()
    def reset_wizard(self) -> None:
        self.config.reset_config()
        self.currentIdChanged.disconnect()
        self._reset_wizard_pages()
        self._remove_all_pages()
        self._insert_plugin_page()
        self._build_wizard_pages()
        self._set_start_page()
        self._connect_current_id_changed()
        self._set_disabled(False)
        self.process_button.setText("Process (Dupe Check)")
        self.process_button.show()
        self.setButtonLayout(self.starting_buttons)
        self.restart()

    def _reset_wizard_pages(self) -> None:
        for page in self._PAGES:
            page.reset_page()

    def _build_wizard_pages(self) -> None:
        for idx, page in enumerate(self._PAGES):
            self.setPage(idx + 1, page)

    def _set_start_page(self) -> None:
        get_profile = self.config.cfg_payload.profile
        profile = Profile(get_profile)
        if not get_profile or profile == Profile.BASIC:
            self.setStartId(WizardPages.BASIC_INPUT_PAGE.value)
            self.main_window.update_status_bar_label.emit("Profile: Basic")

        elif profile == Profile.ADVANCED:
            self.setStartId(WizardPages.ADVANCED_INPUT_PAGE.value)
            self.main_window.update_status_bar_label.emit("Profile: Advanced")

        elif (
            profile == Profile.PLUGIN
            and self.config.cfg_payload.wizard_page
            and self.config.loaded_plugins
        ):
            self.setStartId(WizardPages.PLUGIN_INPUT_PAGE.value)
            self.main_window.update_status_bar_label.emit("Profile: Plugin")

    @Slot(int)
    def _handle_page_change(self, idx: int) -> None:
        if idx > -1 and WizardPages(idx) in self._START_PAGES:
            self.setButtonLayout(self.starting_buttons)
        else:
            if idx != WizardPages.PROCESS_PAGE.value:
                self.setButtonLayout(self.mid_flow_buttons)
            else:
                self.setButtonLayout(self.ending_buttons)

    def _set_disabled(self, value: bool) -> None:
        self.settings_button.setDisabled(value)
        self.next_button.setDisabled(value)

    def end_early(self) -> None:
        self.setButtonLayout(self.ending_buttons)

    def _insert_plugin_page(self) -> None:
        if self.config.cfg_payload.wizard_page and self.config.loaded_plugins:
            try:
                plugin_obj = self.config.loaded_plugins[
                    self.config.cfg_payload.wizard_page
                ]
                if plugin_obj.wizard:
                    plugin_wizard = plugin_obj.wizard(self.config, self.main_window)
                    self._PAGES.pop(WizardPages.PLUGIN_INPUT_PAGE.value - 1)
                    self._PAGES.insert(
                        WizardPages.PLUGIN_INPUT_PAGE.value - 1, plugin_wizard
                    )
            except KeyError:
                return

    def _remove_all_pages(self) -> None:
        for page_id in reversed(self.pageIds()):
            self.removePage(page_id)

    def _connect_current_id_changed(self) -> None:
        self.currentIdChanged.connect(self._handle_page_change)

    def _flow_production(self, current_page: WizardPages) -> int:
        if current_page in self._START_PAGES:
            return WizardPages.MEDIA_SEARCH_PAGE.value

        elif current_page == WizardPages.MEDIA_SEARCH_PAGE:
            if self.config.cfg_payload.mvr_enabled:
                return WizardPages.RENAME_ENCODE_PAGE.value
            elif (
                not self.config.cfg_payload.mvr_enabled
                and self.config.cfg_payload.screenshots_enabled
            ):
                return WizardPages.IMAGES_PAGE.value
            else:
                return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.RENAME_ENCODE_PAGE:
            if self.config.cfg_payload.screenshots_enabled:
                return WizardPages.IMAGES_PAGE.value
            else:
                return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.IMAGES_PAGE:
            return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.TRACKERS_PAGE:
            return WizardPages.NFO_TEMPLATE_PAGE.value

        elif current_page == WizardPages.NFO_TEMPLATE_PAGE:
            return WizardPages.OVERVIEW_PAGE.value

        elif current_page == WizardPages.OVERVIEW_PAGE:
            return WizardPages.PROCESS_PAGE.value

        elif current_page == WizardPages.PROCESS_PAGE:
            return -1

        return -1

    def _flow_dev(self, current_page: WizardPages) -> int:
        if current_page in self._START_PAGES:
            return WizardPages.MEDIA_SEARCH_PAGE.value

        elif current_page == WizardPages.MEDIA_SEARCH_PAGE:
            if self.config.cfg_payload.mvr_enabled:
                return WizardPages.RENAME_ENCODE_PAGE.value
            elif (
                not self.config.cfg_payload.mvr_enabled
                and self.config.cfg_payload.screenshots_enabled
            ):
                return WizardPages.IMAGES_PAGE.value
            else:
                return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.RENAME_ENCODE_PAGE:
            if self.config.cfg_payload.screenshots_enabled:
                return WizardPages.IMAGES_PAGE.value
            else:
                return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.IMAGES_PAGE:
            return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.TRACKERS_PAGE:
            return WizardPages.NFO_TEMPLATE_PAGE.value

        elif current_page == WizardPages.NFO_TEMPLATE_PAGE:
            return WizardPages.OVERVIEW_PAGE.value

        elif current_page == WizardPages.OVERVIEW_PAGE:
            return WizardPages.PROCESS_PAGE.value

        elif current_page == WizardPages.PROCESS_PAGE:
            return -1

        return -1
