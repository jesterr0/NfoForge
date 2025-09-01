from pathlib import Path
import shutil

from PySide6.QtCore import QSize, QTimer, Qt, Slot
from PySide6.QtGui import QWheelEvent
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

from src.backend.utils.file_utilities import (
    file_bytes_to_str,
    get_dir_size,
    open_explorer,
)
from src.enums.logging_settings import LogLevel
from src.enums.settings_window import SettingsTabs
from src.enums.theme import NfoForgeTheme
from src.enums.tmdb_languages import TMDBLanguage
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.global_signals import GSigs
from src.frontend.stacked_windows.settings.base import BaseSettings
from src.frontend.utils import build_h_line, create_form_layout
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from src.logger.nfo_forge_logger import LOG


class GeneralSettings(BaseSettings):
    def __init__(self, config, main_window, parent) -> None:
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
        self.ui_scale_factor_spinbox.wheelEvent = self._disable_scrollwheel_spinbox
        self.ui_scale_factor_spinbox.valueChanged.connect(self._on_scale_factor_changed)
        GSigs().scale_factor_changed.connect(self.sync_scale_factor_spinbox)

        theme_lbl = QLabel("Theme", self)
        theme_lbl.setToolTip("Sets theme")
        self.theme_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )
        self.theme_combo.activated.connect(self._change_theme)

        self.enable_plugins = QCheckBox("Enable External Plugins", self)
        self.enable_plugins.clicked.connect(self._enable_plugins)

        plugin_wizard_page_lbl = QLabel("Choose Wizard Input Page", self)
        plugin_wizard_page_lbl.setToolTip(
            "Choose which wizard input page plugin will be used"
        )
        self.plugin_wizard_page_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )
        plugin_wizard_page_layout = create_form_layout(
            plugin_wizard_page_lbl, self.plugin_wizard_page_combo, (12, 0, 0, 0)
        )

        plugin_wizard_token_replacer_lbl = QLabel("Choose Token Replacer", self)
        plugin_wizard_token_replacer_lbl.setToolTip(
            "Choose which Token Replacer plugin will be used"
        )
        self.plugin_token_replacer_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )
        plugin_token_replacer_layout = create_form_layout(
            plugin_wizard_token_replacer_lbl,
            self.plugin_token_replacer_combo,
            (12, 0, 0, 0),
        )

        plugin_pre_upload_lbl = QLabel("Pre Upload Processing", self)
        plugin_pre_upload_lbl.setToolTip(
            "Choose which pre upload processing plugin will be used"
        )
        self.plugin_pre_upload_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )
        pre_upload_processing_layout = create_form_layout(
            plugin_pre_upload_lbl,
            self.plugin_pre_upload_combo,
            (12, 0, 0, 0),
        )

        self._plugin_widgets = (
            plugin_wizard_page_lbl,
            self.plugin_wizard_page_combo,
            plugin_wizard_token_replacer_lbl,
            self.plugin_token_replacer_combo,
            plugin_pre_upload_lbl,
            self.plugin_pre_upload_combo,
        )

        releasers_name_lbl = QLabel("Releasers Name")
        releasers_name_lbl.setToolTip("Sets the releaser's name. As displayed in NFOs")
        self.releasers_name_entry = QLineEdit(self)

        global_timeout_lbl = QLabel("Global Timeout", self)
        global_timeout_lbl.setToolTip("Sets global timeout for network requests")
        self.global_timeout_spinbox = QSpinBox(self)
        self.global_timeout_spinbox.setRange(2, 120)
        self.global_timeout_spinbox.wheelEvent = self._disable_scrollwheel_spinbox

        tmdb_language_lbl = QLabel("TMDB Language", self)
        tmdb_language_lbl.setToolTip(
            "Sets the language for TMDB API responses (movie/tv metadata, plot text, etc.)"
        )
        self.tmdb_language_combo = CustomComboBox(
            completer=True, completer_strict=True, disable_mouse_wheel=True, parent=self
        )
        self.tmdb_language_combo.activated.connect(self._handle_language_selection)

        self.enable_prompt_overview = QCheckBox("Prompt for Overview", self)
        self.enable_prompt_overview.setToolTip(
            "If enabled during processing an editable overview will pop up allowing the user to make final edits"
        )

        self.enable_mkbrr = QCheckBox("Enable mkbrr", self)
        self.enable_mkbrr.setToolTip(
            "If mkbrr is detected torrent generation will be "
            "completed by mkbrr\n(will fall back to torf if failure is detected)"
        )
        check_mkbrr = QToolButton(self)
        QTAThemeSwap().register(check_mkbrr, "ph.eye-light", icon_size=QSize(20, 20))
        check_mkbrr.setToolTip("Navigate to Dependencies settings tab")
        check_mkbrr.clicked.connect(self._swap_dep_tab)
        mkbrr_widget = QWidget()
        mkbrr_h_box = QHBoxLayout(mkbrr_widget)
        mkbrr_h_box.setContentsMargins(0, 0, 0, 0)
        mkbrr_h_box.addWidget(self.enable_mkbrr)
        mkbrr_h_box.addWidget(check_mkbrr, alignment=Qt.AlignmentFlag.AlignRight)

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
        self.max_log_files_spinbox.wheelEvent = self._disable_scrollwheel_spinbox

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

        self.add_layout(create_form_layout(config_lbl, config_widget))
        self.add_layout(create_form_layout(suffix_lbl, self.ui_suffix))
        self.add_layout(
            create_form_layout(scale_factor_lbl, self.ui_scale_factor_spinbox)
        )
        self.add_layout(create_form_layout(theme_lbl, self.theme_combo))
        self.add_layout(create_form_layout(self.enable_plugins))
        self.add_layout(plugin_wizard_page_layout)
        self.add_layout(plugin_token_replacer_layout)
        self.add_layout(pre_upload_processing_layout)
        self.add_layout(
            create_form_layout(releasers_name_lbl, self.releasers_name_entry)
        )
        self.add_layout(
            create_form_layout(global_timeout_lbl, self.global_timeout_spinbox)
        )
        self.add_widget(build_h_line((10, 1, 10, 1)))
        self.add_layout(create_form_layout(tmdb_language_lbl, self.tmdb_language_combo))
        self.add_widget(build_h_line((10, 1, 10, 1)))
        self.add_layout(create_form_layout(self.enable_prompt_overview))
        self.add_layout(create_form_layout(mkbrr_widget))
        self.add_widget(build_h_line((10, 1, 10, 1)))
        self.add_layout(create_form_layout(log_level_lbl, self.log_level_combo))
        self.add_layout(
            create_form_layout(max_log_files_lbl, self.max_log_files_spinbox)
        )
        self.add_layout(create_form_layout(open_logs_lbl, log_btn_widget))
        self.add_widget(build_h_line((10, 1, 10, 1)))
        self.add_layout(create_form_layout(working_dir_lbl, working_dir_widget))
        self.add_layout(self.reset_layout)

        self._load_saved_settings()

    @Slot()
    def _load_saved_settings(self) -> None:
        """Applies user saved settings from the config"""
        payload = self.config.cfg_payload
        self.load_selected_configs()
        self.ui_suffix.setText(payload.ui_suffix.strip())
        self.ui_scale_factor_spinbox.setValue(int(payload.ui_scale_factor * 100))
        self.load_combo_box(self.theme_combo, NfoForgeTheme, payload.nfo_forge_theme)
        self._change_theme()
        self.enable_plugins.setChecked(payload.enable_plugins)
        self._enable_plugins()
        self.releasers_name_entry.setText(payload.releasers_name)
        self.global_timeout_spinbox.setValue(payload.timeout)
        self._load_tmdb_language_combo(payload.tmdb_language)
        self.enable_prompt_overview.setChecked(payload.enable_prompt_overview)
        self.enable_mkbrr.setChecked(payload.enable_mkbrr)
        self.load_combo_box(self.log_level_combo, LogLevel, payload.log_level)
        self.max_log_files_spinbox.setValue(payload.log_total)
        self.working_dir_entry.setText(
            str(payload.working_dir) if payload.working_dir else ""
        )

    def load_selected_configs(self) -> None:
        self.selected_config.clear()
        for config_file in self.config.USER_CONFIG_DIR.glob("*.toml"):
            self.selected_config.addItem(config_file.stem)

        if self.config.program_conf.current_config:
            current_index = self.selected_config.findText(
                self.config.program_conf.current_config
            )
            if current_index >= 0:
                self.selected_config.setCurrentIndex(current_index)

    def delete_config(self) -> None:
        config_to_remove = self.selected_config.currentText()
        user_configs = [item for item in self.config.USER_CONFIG_DIR.glob("*.toml")]
        if len(user_configs) > 1:
            last_config = None
            for config_file in user_configs:
                if config_file.stem == config_to_remove:
                    config_file.unlink()
                    break
                else:
                    last_config = config_file.stem

            self.config.program_conf.current_config = last_config
            self.load_selected_configs()
            self._swap_config()
        else:
            QMessageBox.information(self, "Info", "You must have at least one config")

    @Slot(int)
    def _swap_config(self, _: int | None = None) -> None:
        self.config.program_conf.current_config = self.selected_config.currentText()
        self.config.load_config(self.selected_config.currentText())
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
        app = QApplication.instance()
        get_theme = NfoForgeTheme(self.theme_combo.currentData()).theme()
        if get_theme:
            app.styleHints().setColorScheme(get_theme)  # pyright: ignore [reportAttributeAccessIssue, reportOptionalMemberAccess]
        else:
            app.styleHints().unsetColorScheme()  # pyright: ignore [reportAttributeAccessIssue, reportOptionalMemberAccess]

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
    def _enable_plugins(self) -> None:
        if self.enable_plugins.isChecked():
            for widget in self._plugin_widgets:
                widget.show()
                self._load_plugin_combos()
        else:
            for widget in self._plugin_widgets:
                widget.hide()

    @Slot()
    def _handle_working_dir_click(self) -> None:
        wd = QFileDialog.getExistingDirectory(
            parent=self,
            caption="Select Directory",
            dir=str(self.config.cfg_payload.working_dir)
            if self.config.cfg_payload.working_dir
            else "",
        )
        if wd:
            wd = Path(wd)
            self.working_dir_entry.setText(str(wd))
            self.config.cfg_payload.working_dir = wd

    @Slot()
    def _handle_open_working_dir_click(self) -> None:
        open_explorer(self.config.cfg_payload.working_dir)

    @Slot()
    def _handle_working_dir_clean_up_click(self) -> None:
        total_size = get_dir_size(self.config.cfg_payload.working_dir)

        msg = (
            "Would you like to clean up the working directory now?\n\n"
            f"Size: {file_bytes_to_str(total_size)}\n\n"
            "WARNING: This will remove all data!"
        )

        if (
            QMessageBox.question(
                self,
                "Clean Up",
                msg,
            )
            is QMessageBox.StandardButton.Yes
        ):
            for item in self.config.cfg_payload.working_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

    @Slot()
    def _swap_dep_tab(self):
        GSigs().settings_swap_tab.emit(SettingsTabs.DEPENDENCIES_SETTINGS)

    def _load_plugin_combos(self) -> None:
        if self.plugin_wizard_page_combo.count() == 0:
            if self.config.loaded_plugins:
                for plugin in self.config.loaded_plugins.values():
                    plugin_name = plugin.name

                    if plugin.wizard:
                        self.plugin_wizard_page_combo.addItem(plugin_name, plugin_name)

                    if plugin.token_replacer is not None:
                        if plugin.token_replacer is False:
                            self.plugin_token_replacer_combo.addItem(plugin_name, None)
                        else:
                            self.plugin_token_replacer_combo.addItem(
                                plugin_name, plugin_name
                            )

                    if plugin.pre_upload is not None:
                        if plugin.pre_upload is False:
                            self.plugin_pre_upload_combo.addItem(plugin_name, None)
                        else:
                            self.plugin_pre_upload_combo.addItem(
                                plugin_name, plugin_name
                            )

        self._apply_plugin_combos_settings()

    def _apply_plugin_combos_settings(self) -> None:
        wizard_plugin = None
        if self.config.cfg_payload.wizard_page:
            wizard_plugin = self.plugin_wizard_page_combo.findText(
                self.config.cfg_payload.wizard_page
            )
        self.plugin_wizard_page_combo.setCurrentIndex(
            wizard_plugin if wizard_plugin and wizard_plugin > 0 else 0
        )

        url_plugin = None
        if self.config.cfg_payload.token_replacer:
            url_plugin = self.plugin_token_replacer_combo.findText(
                self.config.cfg_payload.token_replacer
            )
        self.plugin_token_replacer_combo.setCurrentIndex(
            url_plugin if url_plugin and url_plugin > 0 else 0
        )

        pre_upload_plugin = None
        if self.config.cfg_payload.pre_upload:
            pre_upload_plugin = self.plugin_pre_upload_combo.findText(
                self.config.cfg_payload.pre_upload
            )
        self.plugin_pre_upload_combo.setCurrentIndex(
            pre_upload_plugin if pre_upload_plugin and pre_upload_plugin > 0 else 0
        )

    @Slot()
    def _save_settings(self) -> None:
        self.config.program_conf.current_config = self.selected_config.currentText()
        self.config.cfg_payload.ui_suffix = self.ui_suffix.text().strip()
        self.config.cfg_payload.ui_scale_factor = (
            self.ui_scale_factor_spinbox.value() / 100.0
        )
        self.config.cfg_payload.nfo_forge_theme = NfoForgeTheme(
            self.theme_combo.currentData()
        )
        self.config.cfg_payload.enable_plugins = self.enable_plugins.isChecked()
        if self.enable_plugins.isChecked():
            self.config.cfg_payload.wizard_page = (
                self.plugin_wizard_page_combo.currentData()
            )
            self.config.cfg_payload.token_replacer = (
                self.plugin_token_replacer_combo.currentData()
            )
            self.config.cfg_payload.pre_upload = (
                self.plugin_pre_upload_combo.currentData()
            )
        else:
            self.config.cfg_payload.wizard_page = ""
            self.config.cfg_payload.token_replacer = ""
            self.config.cfg_payload.pre_upload = ""
        self.config.cfg_payload.releasers_name = (
            self.releasers_name_entry.text().strip()
        )
        self.config.cfg_payload.tmdb_language = self.tmdb_language_combo.currentData()
        self.config.cfg_payload.timeout = self.global_timeout_spinbox.value()
        self.config.cfg_payload.enable_prompt_overview = (
            self.enable_prompt_overview.isChecked()
        )
        self.config.cfg_payload.enable_mkbrr = self.enable_mkbrr.isChecked()
        self.config.cfg_payload.log_level = LogLevel(self.log_level_combo.currentData())
        LOG.set_log_level(self.config.cfg_payload.log_level)
        self.config.cfg_payload.log_total = self.max_log_files_spinbox.value()
        self.config.cfg_payload.working_dir = Path(self.working_dir_entry.text())
        self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self.selected_config.setCurrentIndex(0)
        self.ui_suffix.clear()
        self.ui_scale_factor_spinbox.setValue(
            int(self.config.cfg_payload_defaults.ui_scale_factor * 100)
        )
        self.theme_combo.setCurrentIndex(
            self.config.cfg_payload_defaults.nfo_forge_theme.value - 1
        )
        self.enable_plugins.setChecked(False)
        self._enable_plugins()
        self.plugin_wizard_page_combo.clear()
        self.plugin_token_replacer_combo.clear()
        self.releasers_name_entry.clear()
        # set TMDB language to default
        for i in range(self.tmdb_language_combo.count()):
            if (
                self.tmdb_language_combo.itemData(i)
                == self.config.cfg_payload_defaults.tmdb_language
            ):
                self.tmdb_language_combo.setCurrentIndex(i)
                break
        self.global_timeout_spinbox.setValue(self.config.cfg_payload_defaults.timeout)
        self.enable_prompt_overview.setChecked(
            self.config.cfg_payload.enable_prompt_overview
        )
        self.enable_mkbrr.setChecked(self.config.cfg_payload_defaults.enable_mkbrr)
        self.working_dir_entry.setText(str(self.config.default_working_dir()))

    @staticmethod
    def _disable_scrollwheel_spinbox(event: QWheelEvent) -> None:
        event.ignore()
