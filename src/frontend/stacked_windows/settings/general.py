from dataclasses import fields

from PySide6.QtCore import Slot, QTimer
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QCheckBox,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from src.enums.theme import NfoForgeTheme
from src.enums.profile import Profile
from src.enums.media_mode import MediaMode
from src.enums.image_host import ImageHost
from src.enums.logging_settings import LogLevel
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.image_hosts import ImageHostStackedWidget
from src.frontend.custom_widgets.ext_filter_widget import ExtFilterWidget
from src.frontend.stacked_windows.settings.base import BaseSettings


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

        theme_lbl = QLabel("Theme", self)
        theme_lbl.setToolTip("Sets theme")
        self.theme_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )
        self.theme_combo.activated.connect(self._change_theme)

        profile_lbl = QLabel("Profile", self)
        profile_lbl.setToolTip("Sets workflow profile")
        self.profile_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )
        self.profile_combo.activated.connect(self._change_profile)

        plugin_wizard_page_lbl = QLabel("Choose Wizard Input Page", self)
        plugin_wizard_page_lbl.setToolTip(
            "Choose which wizard input page plugin will be used"
        )
        self.plugin_wizard_page_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )
        plugin_wizard_page_layout = self.create_form_layout(
            plugin_wizard_page_lbl, self.plugin_wizard_page_combo, (12, 0, 0, 0)
        )

        plugin_wizard_token_replacer_lbl = QLabel("Choose Token Replacer", self)
        plugin_wizard_token_replacer_lbl.setToolTip(
            "Choose which Token Replacer plugin will be used"
        )
        self.plugin_token_replacer_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )
        plugin_token_replacer_layout = self.create_form_layout(
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
        pre_upload_processing_layout = self.create_form_layout(
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

        media_mode_lbl = QLabel("Media Mode", self)
        media_mode_lbl.setToolTip(
            "Sets media processing mode (locked to 'Movies' until support is added)"
        )
        self.media_mode_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )
        # TODO: remove when TV support is added and modify tooltip
        self.media_mode_combo.setDisabled(True)

        self.source_ext_filter = ExtFilterWidget(
            label_text="Filter Source Media Extensions (Basic 'Input')",
            tool_tip="Modify allowed source extensions (Basic 'Input')",
            parent=self,
        )

        self.encode_ext_filter = ExtFilterWidget(
            label_text="Filter Encode Media Extensions (Advanced 'Encode')",
            tool_tip="Filter Encode Media Extensions (Advanced 'Encode')",
            parent=self,
        )

        dir_toggle_lbl = QLabel("Directory Input")
        dir_toggle_lbl.setToolTip(
            "Toggle if we're accepting a directory of file(s) or a single file"
        )
        self.dir_toggle_btn = QCheckBox(self)

        releasers_name_lbl = QLabel("Releasers Name")
        releasers_name_lbl.setToolTip("Sets the releaser's name. As displayed in NFOs")
        self.releasers_name_entry = QLineEdit(self)

        image_host_selection_lbl = QLabel("Image Host", self)
        image_host_selection_lbl.setToolTip(
            "Sets desired image host to upload screenshots to"
        )
        self.image_host_selection = ImageHostStackedWidget(self.config, self)

        global_timeout_lbl = QLabel("Global Timeout", self)
        global_timeout_lbl.setToolTip("Sets global timeout for network requests")
        self.global_timeout_spinbox = QSpinBox(self)
        self.global_timeout_spinbox.setRange(2, 120)
        self.global_timeout_spinbox.wheelEvent = self._disable_scrollwheel_spinbox

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

        view_log_files_btn = QPushButton("View Log Files", self)
        view_log_files_btn.clicked.connect(self.main_window.open_log_dir.emit)

        self.add_layout(self.create_form_layout(config_lbl, config_widget))
        self.add_layout(self.create_form_layout(suffix_lbl, self.ui_suffix))
        self.add_layout(self.create_form_layout(theme_lbl, self.theme_combo))
        self.add_layout(self.create_form_layout(profile_lbl, self.profile_combo))
        self.add_layout(plugin_wizard_page_layout)
        self.add_layout(plugin_token_replacer_layout)
        self.add_layout(pre_upload_processing_layout)
        self.add_layout(self.create_form_layout(media_mode_lbl, self.media_mode_combo))
        self.add_widget(self.source_ext_filter)
        self.add_widget(self.encode_ext_filter)
        self.add_layout(self.create_form_layout(dir_toggle_lbl, self.dir_toggle_btn))
        self.add_layout(
            self.create_form_layout(releasers_name_lbl, self.releasers_name_entry)
        )
        self.add_layout(
            self.create_form_layout(image_host_selection_lbl, self.image_host_selection)
        )
        self.add_layout(
            self.create_form_layout(global_timeout_lbl, self.global_timeout_spinbox)
        )
        self.add_layout(self.create_form_layout(log_level_lbl, self.log_level_combo))
        self.add_layout(
            self.create_form_layout(max_log_files_lbl, self.max_log_files_spinbox)
        )
        self.add_layout(self.create_form_layout(view_log_files_btn))
        self.add_layout(self.reset_layout)

        self._load_saved_settings()

    @Slot()
    def _load_saved_settings(self) -> None:
        """Applies user saved settings from the config"""
        payload = self.config.cfg_payload
        self.load_selected_configs()
        self.ui_suffix.setText(payload.ui_suffix.strip())
        self.load_combo_box(self.theme_combo, NfoForgeTheme, payload.nfo_forge_theme)
        self._change_theme()
        self.load_combo_box(self.profile_combo, Profile, payload.profile)
        self._change_profile()
        self.load_combo_box(self.media_mode_combo, MediaMode, payload.media_mode)
        self._load_filter_widget(
            user_settings=payload.source_media_ext_filter,
            filter_widget=self.source_ext_filter,
        )
        self._load_filter_widget(
            user_settings=payload.encode_media_ext_filter,
            filter_widget=self.encode_ext_filter,
        )
        self.dir_toggle_btn.setChecked(payload.media_input_dir)
        self.releasers_name_entry.setText(payload.releasers_name)
        self.image_host_selection.build_image_host_config_widgets()
        self.global_timeout_spinbox.setValue(payload.timeout)
        self.load_combo_box(self.log_level_combo, LogLevel, payload.log_level)
        self.max_log_files_spinbox.setValue(payload.log_total)

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
        config_path = (
            self.config.USER_CONFIG_DIR / f"{self.selected_config.currentText()}.toml"
        )
        self.config.program_conf.current_config = config_path.stem
        self.config.load_config(config_path)
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

    def _load_filter_widget(
        self,
        user_settings: list[str] | None,
        filter_widget: ExtFilterWidget,
        defaults: bool = False,
    ) -> None:
        accepted_files = []
        if user_settings and not defaults:
            for item in self.config.ACCEPTED_EXTENSIONS:
                if item in user_settings:
                    accepted_files.append((item, True))
                else:
                    accepted_files.append((item, False))
        else:
            for item in self.config.ACCEPTED_EXTENSIONS:
                accepted_files.append((item, True))
        filter_widget.update_items(accepted_files)

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
    def _change_profile(self, _: int | None = None) -> None:
        if self.profile_combo.currentData() == Profile.PLUGIN:
            for widget in self._plugin_widgets:
                widget.show()
                self._load_plugin_combos()
        else:
            for widget in self._plugin_widgets:
                widget.hide()

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
        self.config.cfg_payload.nfo_forge_theme = NfoForgeTheme(
            self.theme_combo.currentData()
        )
        self.config.cfg_payload.profile = Profile(self.profile_combo.currentData())
        if self.profile_combo.currentData() == Profile.PLUGIN:
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
        self.config.cfg_payload.media_mode = MediaMode(
            self.media_mode_combo.currentData()
        )
        self.config.cfg_payload.source_media_ext_filter = (
            self.source_ext_filter.get_accepted_items()
        )
        self.config.cfg_payload.encode_media_ext_filter = (
            self.encode_ext_filter.get_accepted_items()
        )
        self.config.cfg_payload.media_input_dir = self.dir_toggle_btn.isChecked()
        self.config.cfg_payload.releasers_name = (
            self.releasers_name_entry.text().strip()
        )
        self.config.cfg_payload.image_host = ImageHost(
            self.image_host_selection.image_host_selector.currentData()
        )
        for image_host, payload_obj in self.image_host_selection.get_all_data():
            cur_host = self.config.image_host_map[ImageHost(image_host)]
            for field_info in fields(payload_obj):
                field_name = field_info.name
                field_value = getattr(payload_obj, field_name)
                setattr(cur_host, field_name, field_value)
        self.config.cfg_payload.timeout = self.global_timeout_spinbox.value()
        self.config.cfg_payload.log_level = LogLevel(self.log_level_combo.currentData())
        self.config.cfg_payload.log_total = self.max_log_files_spinbox.value()
        self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self.selected_config.setCurrentIndex(0)
        self.ui_suffix.clear()
        self.theme_combo.setCurrentIndex(0)
        self.profile_combo.setCurrentIndex(0)
        self.plugin_wizard_page_combo.clear()
        self.plugin_token_replacer_combo.clear()
        self.media_mode_combo.setCurrentIndex(0)
        self._load_filter_widget(
            user_settings=None, filter_widget=self.source_ext_filter, defaults=True
        )
        self._load_filter_widget(
            user_settings=None, filter_widget=self.encode_ext_filter, defaults=True
        )
        self.dir_toggle_btn.setChecked(False)
        self.releasers_name_entry.clear()
        self.image_host_selection.reset()
        self.global_timeout_spinbox.setValue(60)

    @staticmethod
    def _disable_scrollwheel_spinbox(event: QWheelEvent) -> None:
        event.ignore()
