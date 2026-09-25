from pathlib import Path
import shutil
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QSpinBox,
    QToolButton,
    QWidget,
)

from nfoforge.backend.utils.file_utilities import (
    file_bytes_to_str,
    open_explorer,
)
from nfoforge.backend.utils.working_dir import cleanable_items, cleanable_size
from nfoforge.config.config import ConfigManager
from nfoforge.enums.logging_settings import LogLevel
from nfoforge.enums.media_search_mode import MediaSearchMode
from nfoforge.enums.theme import NfoForgeTheme
from nfoforge.enums.tmdb_languages import TMDBLanguage
from nfoforge.exceptions import ConfigError, ConfigSchemaError
from nfoforge.frontend.custom_widgets.combo_box import CustomComboBox
from nfoforge.frontend.custom_widgets.masked_qline_edit import MaskedQLineEdit
from nfoforge.frontend.global_signals import GSigs
from nfoforge.frontend.stacked_windows.settings.base import BaseSettings
from nfoforge.frontend.utils import build_h_line, create_form_layout
from nfoforge.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from nfoforge.frontend.windows.config_transfer import (
    export_configuration,
    import_configuration,
)
from nfoforge.frontend.windows.legacy_import import (
    LegacyImportRunner,
    choose_legacy_install,
)
from nfoforge.logger.nfo_forge_logger import LOG

if TYPE_CHECKING:
    from nfoforge.frontend.stacked_windows.settings.settings import Settings
    from nfoforge.frontend.windows.main_window import MainWindow

# `None` leaves the choice to the operating system.
_COLOR_SCHEMES: dict[NfoForgeTheme, Qt.ColorScheme | None] = {
    NfoForgeTheme.AUTOMATIC: None,
    NfoForgeTheme.LIGHT: Qt.ColorScheme.Light,
    NfoForgeTheme.DARK: Qt.ColorScheme.Dark,
}


class GeneralSettings(BaseSettings):
    def __init__(
        self,
        config: ConfigManager,
        main_window: "MainWindow",
        parent: "Settings",
    ) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("generalSettings")

        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)

        config_lbl = QLabel("Config", self)
        config_lbl.setToolTip("Selects current user config")
        self.selected_config = CustomComboBox(disable_mouse_wheel=True, parent=self)
        self.selected_config.activated.connect(self._swap_config)
        self.del_config_btn = QPushButton("Delete", self)
        self.del_config_btn.clicked.connect(self._delete_config)
        self.del_button_timer = QTimer()
        self.del_button_timer.timeout.connect(self._reset_del_btn)
        config_widget = QWidget()
        config_layout = QHBoxLayout(config_widget)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.addWidget(self.selected_config, stretch=1)
        config_layout.addWidget(self.del_config_btn)

        suffix_lbl = QLabel("UI Suffix", self)
        suffix_lbl.setToolTip("Adds a suffix to NfoForge")
        self.ui_suffix = QLineEdit(self)

        scale_factor_lbl = QLabel("UI Scale Factor", self)
        scale_factor_lbl.setToolTip(
            "Adjusts the overall UI scaling (50% - 300%).\n"
            "Use Ctrl++ / Ctrl+- to zoom in and out on the fly.\n(CTRL+0 resets to default)"
        )
        self.ui_scale_factor_spinbox = QSpinBox(
            self, suffix="%", singleStep=10, minimum=50, maximum=300
        )
        self.ui_scale_factor_spinbox.setToolTip(scale_factor_lbl.toolTip())
        self.ui_scale_factor_spinbox.lineEdit().setReadOnly(True)
        self._disable_scrollwheel_spinbox(self.ui_scale_factor_spinbox)
        self.ui_scale_factor_spinbox.valueChanged.connect(self._on_scale_factor_changed)
        GSigs().scale_factor_changed.connect(self.sync_scale_factor_spinbox)

        theme_lbl = QLabel("Theme", self)
        theme_lbl.setToolTip("Sets theme")
        self.theme_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )
        self.theme_combo.activated.connect(self._change_theme)

        releasers_name_lbl = QLabel("Releasers Name")
        releasers_name_lbl.setToolTip("Sets the releaser's name. As displayed in NFOs")
        self.releasers_name_entry = QLineEdit(self)

        release_group_lbl = QLabel("Release Group")
        release_group_lbl.setToolTip(
            "Your group tag, printed by the {release_group} token in filenames, "
            "titles and NFOs. Pre-fills the rename page, where it can still be "
            "changed for a one-off release. Leave blank to take the group from "
            "the input filename instead."
        )
        self.release_group_entry = QLineEdit(self)
        self.release_group_entry.setToolTip(release_group_lbl.toolTip())
        self.release_group_entry.setPlaceholderText("No group tag")

        global_timeout_lbl = QLabel("Global Timeout", self)
        global_timeout_lbl.setToolTip("Sets global timeout for network requests")
        self.global_timeout_spinbox = QSpinBox(self)
        self.global_timeout_spinbox.setRange(2, 120)
        self._disable_scrollwheel_spinbox(self.global_timeout_spinbox)

        tmdb_language_lbl = QLabel("TMDB Language", self)
        tmdb_language_lbl.setToolTip(
            "Sets the language for TMDB API responses (movie/tv metadata, plot text, etc.)"
        )
        self.tmdb_language_combo = CustomComboBox(
            completer=True, completer_strict=True, disable_mouse_wheel=True, parent=self
        )
        self.tmdb_language_combo.activated.connect(self._handle_language_selection)

        media_search_mode_lbl = QLabel("Media Search Type", self)
        media_search_mode_lbl.setToolTip(
            "Controls whether title searches return movies, TV shows, or both.\n\nNote: this controls the "
            "flow of the rest of the program and essentially disables what ever is not selected"
        )
        self.media_search_mode_combo = CustomComboBox(
            disable_mouse_wheel=True, parent=self
        )
        self.media_search_mode_combo.setToolTip(media_search_mode_lbl.toolTip())

        tmdb_api_key_lbl = QLabel("TMDB API Key", self)
        tmdb_api_key_lbl.setToolTip(
            "Optional. Leave blank to use the key bundled with NfoForge.\n"
            "Supply your own TMDB v3 API key to make requests under your own "
            "account instead."
        )
        self.tmdb_api_key_entry = MaskedQLineEdit(parent=self, masked=True)
        self.tmdb_api_key_entry.setPlaceholderText("Using bundled key")

        self.enable_prompt_overview = QCheckBox("Prompt for Overview", self)
        self.enable_prompt_overview.setToolTip(
            "If enabled processing pauses on an overview of each tracker's title and NFO\n"
            "(titles are shown for review, NFOs can be edited)"
        )

        self.check_for_updates = QCheckBox("Check for Updates", self)
        self.check_for_updates.setToolTip(
            "Periodically checks GitHub for a newer NfoForge release and "
            "shows a link in the status bar when one is available"
        )

        log_level_lbl = QLabel("Log Level", self)
        log_level_lbl.setToolTip("Sets minimum log level")

        self.log_level_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )

        max_log_files_lbl = QLabel("Max Log Files", self)
        max_log_files_lbl.setToolTip(
            "Maximum number of log files to keep (clean up runs after NfoForge is launched)"
        )

        self.max_log_files_spinbox = QSpinBox(self)
        self.max_log_files_spinbox.setRange(10, 500)
        self._disable_scrollwheel_spinbox(self.max_log_files_spinbox)

        open_logs_lbl = QLabel("View Logs", self)
        self.open_log_directory = QToolButton(self)
        QTAThemeSwap().register(
            self.open_log_directory, "ph.files-light", icon_size=QSize(20, 20)
        )
        self.open_log_directory.setToolTip("Open log directory")
        self.open_log_directory.clicked.connect(GSigs().main_window_open_log_dir.emit)

        self.open_log_file = QToolButton(self)
        QTAThemeSwap().register(
            self.open_log_file, "ph.file-arrow-down-light", icon_size=QSize(20, 20)
        )
        self.open_log_file.setToolTip(
            "Open log file if exists otherwise will open the log directory"
        )
        self.open_log_file.clicked.connect(GSigs().main_window_open_log_file.emit)

        log_btn_widget = QWidget()
        log_btn_layout = QHBoxLayout(log_btn_widget)
        log_btn_layout.setContentsMargins(0, 0, 0, 0)
        log_btn_layout.addWidget(self.open_log_directory)
        log_btn_layout.addWidget(self.open_log_file)
        log_btn_layout.addSpacerItem(
            QSpacerItem(
                1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
        )

        working_dir_lbl = QLabel("Working Directory", self)
        self.working_dir_entry = QLineEdit(self)
        self.working_dir_entry.setReadOnly(True)
        self.working_dir_entry.setToolTip(
            "Working files (torrents, images, etc.) will be placed inside of this folder for each job"
        )
        self.working_dir_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.working_dir_btn, "ph.folder-open-light", icon_size=QSize(20, 20)
        )
        self.working_dir_btn.setToolTip("Set working directory")
        self.working_dir_btn.clicked.connect(self._handle_working_dir_click)

        self.working_dir_open_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.working_dir_open_btn, "ph.eye-light", icon_size=QSize(20, 20)
        )
        self.working_dir_open_btn.setToolTip("Open working directory")
        self.working_dir_open_btn.clicked.connect(self._handle_open_working_dir_click)

        self.working_dir_clean_up = QToolButton(self)
        QTAThemeSwap().register(
            self.working_dir_clean_up, "ph.trash-light", icon_size=QSize(20, 20)
        )
        self.working_dir_clean_up.setToolTip("Clean up working directory")
        self.working_dir_clean_up.clicked.connect(
            self._handle_working_dir_clean_up_click
        )

        working_dir_widget = QWidget()
        working_dir_layout = QHBoxLayout(working_dir_widget)
        working_dir_layout.setContentsMargins(0, 0, 0, 0)
        working_dir_layout.addWidget(self.working_dir_entry, stretch=1)
        working_dir_layout.addWidget(self.working_dir_btn)
        working_dir_layout.addWidget(self.working_dir_open_btn)
        working_dir_layout.addWidget(self.working_dir_clean_up)

        data_dir_lbl = QLabel("Data Folder", self)
        self.data_dir_entry = QLineEdit(self)
        self.data_dir_entry.setReadOnly(True)
        self.data_dir_entry.setText(str(self.config.paths.state_root))
        self.data_dir_entry.setToolTip(
            "Your settings, profiles, templates, plugins and tools live here, "
            "outside the application, so replacing a release does not disturb them"
        )

        self.data_dir_open_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.data_dir_open_btn, "ph.eye-light", icon_size=QSize(20, 20)
        )
        self.data_dir_open_btn.setToolTip("Open data folder")
        self.data_dir_open_btn.clicked.connect(self._handle_open_data_dir_click)

        self.import_legacy_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.import_legacy_btn, "ph.download-simple-light", icon_size=QSize(20, 20)
        )
        self.import_legacy_btn.setToolTip("Import from a previous installation")
        self.import_legacy_btn.clicked.connect(self._handle_import_legacy_click)

        self.export_config_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.export_config_btn, "ph.export-light", icon_size=QSize(20, 20)
        )
        self.export_config_btn.setToolTip(
            "Export profiles and their templates to a bundle you can copy to "
            "another machine or share"
        )
        self.export_config_btn.clicked.connect(self._handle_export_config_click)

        self.import_config_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.import_config_btn, "ph.file-arrow-down-light", icon_size=QSize(20, 20)
        )
        self.import_config_btn.setToolTip("Import a configuration bundle")
        self.import_config_btn.clicked.connect(self._handle_import_config_click)

        data_dir_widget = QWidget()
        data_dir_layout = QHBoxLayout(data_dir_widget)
        data_dir_layout.setContentsMargins(0, 0, 0, 0)
        data_dir_layout.addWidget(self.data_dir_entry, stretch=1)
        data_dir_layout.addWidget(self.data_dir_open_btn)
        data_dir_layout.addWidget(self.import_legacy_btn)
        data_dir_layout.addWidget(self.export_config_btn)
        data_dir_layout.addWidget(self.import_config_btn)

        self.add_layout(create_form_layout(config_lbl, config_widget))
        self.add_layout(create_form_layout(suffix_lbl, self.ui_suffix))
        self.add_layout(
            create_form_layout(scale_factor_lbl, self.ui_scale_factor_spinbox)
        )
        self.add_layout(create_form_layout(theme_lbl, self.theme_combo))
        self.add_layout(
            create_form_layout(releasers_name_lbl, self.releasers_name_entry)
        )
        self.add_layout(create_form_layout(release_group_lbl, self.release_group_entry))
        self.add_layout(
            create_form_layout(global_timeout_lbl, self.global_timeout_spinbox)
        )
        self.add_widget(build_h_line((10, 1, 10, 1)))
        self.add_layout(create_form_layout(tmdb_language_lbl, self.tmdb_language_combo))
        self.add_layout(
            create_form_layout(media_search_mode_lbl, self.media_search_mode_combo)
        )
        self.add_layout(create_form_layout(tmdb_api_key_lbl, self.tmdb_api_key_entry))
        self.add_widget(build_h_line((10, 1, 10, 1)))
        self.add_layout(create_form_layout(self.enable_prompt_overview))
        self.add_layout(create_form_layout(self.check_for_updates))
        self.add_widget(build_h_line((10, 1, 10, 1)))
        self.add_layout(create_form_layout(log_level_lbl, self.log_level_combo))
        self.add_layout(
            create_form_layout(max_log_files_lbl, self.max_log_files_spinbox)
        )
        self.add_layout(create_form_layout(open_logs_lbl, log_btn_widget))
        self.add_widget(build_h_line((10, 1, 10, 1)))
        self.add_layout(create_form_layout(working_dir_lbl, working_dir_widget))
        self.add_layout(create_form_layout(data_dir_lbl, data_dir_widget))
        self.add_layout(self.reset_layout)

        self._load_saved_settings()

    @Slot()
    def _load_saved_settings(self) -> None:
        """Applies user saved settings from the config"""
        payload = self.config.settings.general
        self.load_selected_configs()
        self.ui_suffix.setText(payload.ui_suffix.strip())
        self.ui_scale_factor_spinbox.setValue(int(payload.ui_scale_factor * 100))
        self.load_combo_box(self.theme_combo, NfoForgeTheme, payload.theme)
        self._change_theme()
        self.releasers_name_entry.setText(payload.releasers_name)
        self.release_group_entry.setText(payload.release_group)
        self.global_timeout_spinbox.setValue(payload.timeout)
        self._load_tmdb_language_combo(payload.tmdb_language)
        self.load_combo_box(
            self.media_search_mode_combo,
            MediaSearchMode,
            payload.media_search_mode,
        )
        self.tmdb_api_key_entry.setText(self.config.settings.api_keys.tmdb_api_key)
        self.enable_prompt_overview.setChecked(payload.enable_prompt_overview)
        self.check_for_updates.setChecked(payload.check_for_updates)
        self.load_combo_box(self.log_level_combo, LogLevel, payload.log_level)
        self.max_log_files_spinbox.setValue(payload.log_total)
        self.working_dir_entry.setText(
            str(payload.working_dir) if payload.working_dir else ""
        )

    def load_selected_configs(self) -> None:
        self.selected_config.clear()
        for config_file in self.config.paths.user_configs.glob("*.toml"):
            self.selected_config.addItem(config_file.stem)

        if self.config.program.current_config:
            current_index = self.selected_config.findText(
                self.config.program.current_config
            )
            if current_index >= 0:
                self.selected_config.setCurrentIndex(current_index)

    def delete_config(self) -> None:
        config_to_remove = self.selected_config.currentText()
        user_configs = [item for item in self.config.paths.user_configs.glob("*.toml")]
        if len(user_configs) > 1:
            last_config = None
            for config_file in user_configs:
                if config_file.stem == config_to_remove:
                    config_file.unlink()
                    break
                else:
                    last_config = config_file.stem

            self.config.program.current_config = last_config
            self.load_selected_configs()
            self._swap_config()
        else:
            QMessageBox.information(self, "Info", "You must have at least one config")

    @Slot(int)
    def _swap_config(self, _: int | None = None) -> None:
        previous = self.config.program.current_config
        target = self.selected_config.currentText()
        try:
            self.config.load_profile(target)
        except ConfigSchemaError as error:
            self.selected_config.setCurrentText(previous or "")
            QMessageBox.critical(
                self,
                "Incompatible Config",
                (f"{error}\n\nReverted to the previous config: {previous}"),
            )
            return
        self.settings_window.re_load_settings.emit()

    @Slot()
    def _delete_config(self) -> None:
        if self.del_button_timer.isActive():
            self._reset_del_btn()
            self.delete_config()
        else:
            self.del_config_btn.setText("Confirm?")
            self.del_button_timer.start(3000)

    @Slot()
    def _reset_del_btn(self) -> None:
        self.del_button_timer.stop()
        self.del_config_btn.setText("Delete")

    def _load_tmdb_language_combo(self, current_language: str) -> None:
        """Load TMDB language options into the combo box and set current selection."""
        self.tmdb_language_combo.clear()

        # add all available languages
        for language in TMDBLanguage:
            self.tmdb_language_combo.addItem(language.display_name, language.code)

        # add a separator and custom option
        self.tmdb_language_combo.insertSeparator(self.tmdb_language_combo.count())
        self.tmdb_language_combo.addItem("Custom Language Code...", "CUSTOM")

        # set current selection
        current_index = self.tmdb_language_combo.findData(current_language)
        if current_index >= 0:
            self.tmdb_language_combo.setCurrentIndex(current_index)
        else:
            # check if it's a custom language code not in our enum
            if current_language != "en-US":  # not the default
                # add the custom language as a temporary item
                custom_display = f"Custom: {current_language}"
                self.tmdb_language_combo.insertItem(
                    self.tmdb_language_combo.count() - 2,  # before separator
                    custom_display,
                    current_language,
                )
                # select the custom item
                custom_index = self.tmdb_language_combo.findData(current_language)
                if custom_index >= 0:
                    self.tmdb_language_combo.setCurrentIndex(custom_index)
            else:
                # default to English if not found
                default_index = self.tmdb_language_combo.findData("en-US")
                if default_index >= 0:
                    self.tmdb_language_combo.setCurrentIndex(default_index)

    @Slot(int)
    def _handle_language_selection(self, index: int) -> None:
        """Handle language selection, including custom input option."""
        selected_data = self.tmdb_language_combo.itemData(index)

        if selected_data == "CUSTOM":
            text, ok = QInputDialog.getText(
                self,
                "Custom Language Code",
                "Enter TMDB language code (e.g., 'es-MX', 'pt-BR'):\n\n"
                "Format: language-COUNTRY (ISO 639-1 + ISO 3166-1)\n"
                "Examples: en-US, fr-CA, zh-CN, ar-SA",
                text="en-US",
            )

            if ok and text.strip():
                custom_code = text.strip()
                # validate basic format (language-COUNTRY or just language)
                if (
                    len(custom_code) >= 2
                    and custom_code.replace("-", "").replace("_", "").isalpha()
                ):
                    # normalize format (replace underscores with hyphens)
                    custom_code = custom_code.replace("_", "-")
                    # remove any existing custom entries
                    for i in range(self.tmdb_language_combo.count() - 1, -1, -1):
                        item_data = self.tmdb_language_combo.itemData(i)
                        if item_data and (
                            item_data.startswith("Custom:")
                            or (
                                item_data not in [lang.code for lang in TMDBLanguage]
                                and item_data != "CUSTOM"
                            )
                        ):
                            self.tmdb_language_combo.removeItem(i)

                    # add the new custom language
                    custom_display = f"Custom: {custom_code}"
                    insert_index = (
                        self.tmdb_language_combo.count() - 2
                    )  # Before separator
                    self.tmdb_language_combo.insertItem(
                        insert_index, custom_display, custom_code
                    )
                    self.tmdb_language_combo.setCurrentIndex(insert_index)
                else:
                    # invalid input, revert to previous selection
                    self.tmdb_language_combo.setCurrentIndex(0)
            else:
                # user cancelled, revert to previous selection
                self.tmdb_language_combo.setCurrentIndex(0)

        GSigs().main_window_update_status_tip.emit(
            "Apply changes to reflect TMDB localization in template preview", 10000
        )

    @Slot(int)
    def _change_theme(self, _: int | None = None) -> None:
        """
        For what ever reason ```QApplication.instance()``` doesn't type hint correctly so we
        can ignore these errors for now.
        """
        app = cast(QApplication | None, QApplication.instance())
        if app is None:
            return
        color_scheme = _COLOR_SCHEMES[NfoForgeTheme(self.theme_combo.currentData())]
        if color_scheme:
            app.styleHints().setColorScheme(color_scheme)
        else:
            app.styleHints().unsetColorScheme()

    @Slot(int)
    def _on_scale_factor_changed(self, value: int) -> None:
        """Handle UI scale factor changes from the spinbox."""
        scale_factor = value / 100.0
        # emit global signal to update scaling (no auto-save)
        GSigs().scale_factor_set_from_settings.emit(scale_factor)

    @Slot(float)
    def sync_scale_factor_spinbox(self, scale_factor: float) -> None:
        """Sync the spinbox value when scaling changes via hotkeys."""
        self.ui_scale_factor_spinbox.valueChanged.disconnect()
        self.ui_scale_factor_spinbox.setValue(int(scale_factor * 100))
        self.ui_scale_factor_spinbox.valueChanged.connect(self._on_scale_factor_changed)

    @Slot()
    def _handle_working_dir_click(self) -> None:
        wd = QFileDialog.getExistingDirectory(
            parent=self,
            caption="Select Directory",
            dir=str(self.config.settings.general.working_dir)
            if self.config.settings.general.working_dir
            else "",
        )
        if wd:
            working_dir = Path(wd)
            self.working_dir_entry.setText(str(working_dir))
            self.config.settings.general.working_dir = working_dir

    @Slot()
    def _handle_open_data_dir_click(self) -> None:
        open_explorer(self.config.paths.state_root)

    @Slot()
    def _handle_import_legacy_click(self) -> None:
        """Bring a previous installation's settings in, whenever the user asks.

        Offered permanently rather than only at first launch, so declining the
        migration once is not a decision someone is stuck with -- and so a user
        who upgraded on a different machine, or restored a backup, has a way in.

        Anything whose destination is already occupied is put aside rather than
        replacing what is there, and the summary afterwards says where it went.
        """
        found = choose_legacy_install(self)
        if found is None:
            return

        self._legacy_import_runner = LegacyImportRunner(self.config.paths, self)
        self._legacy_import_runner.start(found)

    @Slot()
    def _handle_export_config_click(self) -> None:
        """Write selected profiles, and their templates, to a bundle.

        Separate from the legacy import beside it, which moves a whole previous
        installation on this machine. This one produces a file that can leave
        it -- so it strips credentials unless the user says otherwise.
        """
        export_configuration(self, self.config)

    @Slot()
    def _handle_import_config_click(self) -> None:
        """Bring a bundle in, then re-read the profile list.

        The list is rebuilt rather than left alone because an import adds
        profiles, and a combo still showing what was there would offer a set
        that no longer matches the directory behind it.
        """
        outcome = import_configuration(self, self.config)
        if outcome is None or not outcome.written:
            return

        self.load_selected_configs()
        active = self.config.program.current_config
        if not active:
            return
        active_path = self.config.paths.user_configs / f"{active}.toml"
        if active_path not in outcome.written:
            return

        # Validation during import is deliberately a dry run, so replacing the
        # profile currently in use leaves the manager and every settings page
        # describing the old document until it is explicitly loaded.  A later
        # Apply would otherwise write that stale document back over the import.
        try:
            self.config.load_profile(active)
        except ConfigError as error:
            QMessageBox.critical(
                self,
                "Reload Imported Profile",
                "The active profile was imported but could not be reloaded:\n\n"
                f"{error}\n\nRestart NfoForge before changing other settings.",
            )
            return
        self.settings_window.re_load_settings.emit()

    @Slot()
    def _handle_open_working_dir_click(self) -> None:
        open_explorer(self.config.settings.general.working_dir)

    @Slot()
    def _handle_working_dir_clean_up_click(self) -> None:
        working_dir = self.config.settings.general.working_dir
        data_root = self.config.paths.data_root()
        removable = cleanable_items(working_dir, data_root)
        total_size = cleanable_size(working_dir, data_root)

        msg = (
            "Would you like to clean up the working directory now?\n\n"
            f"Size: {file_bytes_to_str(total_size)}\n\n"
            "WARNING: This removes all generated data (screenshots, torrents, "
            "and NFOs).\n\nSaved jobs are kept."
        )

        if (
            QMessageBox.question(
                self,
                "Clean Up",
                msg,
            )
            is QMessageBox.StandardButton.Yes
        ):
            for item in removable:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

    @Slot()
    def _save_settings(self) -> None:
        self.config.program.current_config = self.selected_config.currentText()
        self.config.settings.general.ui_suffix = self.ui_suffix.text().strip()
        self.config.settings.general.ui_scale_factor = (
            self.ui_scale_factor_spinbox.value() / 100.0
        )
        self.config.settings.general.theme = NfoForgeTheme(
            self.theme_combo.currentData()
        )
        self.config.settings.general.releasers_name = (
            self.releasers_name_entry.text().strip()
        )
        self.config.settings.general.release_group = (
            self.release_group_entry.text().strip()
        )
        self.config.settings.general.tmdb_language = (
            self.tmdb_language_combo.currentData()
        )
        self.config.settings.general.media_search_mode = MediaSearchMode(
            self.media_search_mode_combo.currentData()
        )
        self.config.settings.api_keys.tmdb_api_key = (
            self.tmdb_api_key_entry.text().strip()
        )
        self.config.settings.general.timeout = self.global_timeout_spinbox.value()
        self.config.settings.general.enable_prompt_overview = (
            self.enable_prompt_overview.isChecked()
        )
        self.config.settings.general.check_for_updates = (
            self.check_for_updates.isChecked()
        )
        self.config.settings.general.log_level = LogLevel(
            self.log_level_combo.currentData()
        )
        LOG.set_log_level(self.config.settings.general.log_level)
        self.config.settings.general.log_total = self.max_log_files_spinbox.value()
        self.config.settings.general.working_dir = Path(self.working_dir_entry.text())
        self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self.selected_config.setCurrentIndex(0)
        self.ui_suffix.clear()
        self.ui_scale_factor_spinbox.setValue(
            int(self.config.defaults.general.ui_scale_factor * 100)
        )
        self.theme_combo.setCurrentIndex(self.config.defaults.general.theme.value - 1)
        self.releasers_name_entry.clear()
        self.release_group_entry.clear()
        # set TMDB language to default
        for i in range(self.tmdb_language_combo.count()):
            if (
                self.tmdb_language_combo.itemData(i)
                == self.config.defaults.general.tmdb_language
            ):
                self.tmdb_language_combo.setCurrentIndex(i)
                break
        self.load_combo_box(
            self.media_search_mode_combo,
            MediaSearchMode,
            self.config.defaults.general.media_search_mode,
        )
        self.tmdb_api_key_entry.clear()
        self.global_timeout_spinbox.setValue(self.config.defaults.general.timeout)
        self.enable_prompt_overview.setChecked(
            self.config.settings.general.enable_prompt_overview
        )
        self.check_for_updates.setChecked(
            self.config.defaults.general.check_for_updates
        )
        self.working_dir_entry.setText(str(self.config.defaults.general.working_dir))

    def _disable_scrollwheel_spinbox(self, spinbox: QSpinBox) -> None:
        spinbox.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QSpinBox) and event.type() is QEvent.Type.Wheel:
            event.ignore()
            return True
        return bool(super().eventFilter(watched, event))
