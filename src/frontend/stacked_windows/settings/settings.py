from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.backend.main_window import restart_application
from src.config.config import ConfigManager
from src.config.dependencies import unavailable_screenshot_dependency
from src.enums.dependencies import Dependencies
from src.enums.settings_window import SettingsTabs
from src.frontend.global_signals import GSigs
from src.frontend.stacked_windows.settings.about import AboutTab
from src.frontend.stacked_windows.settings.base import BaseSettings
from src.frontend.stacked_windows.settings.clients import ClientsSettings
from src.frontend.stacked_windows.settings.dependencies import DependencySettings
from src.frontend.stacked_windows.settings.general import GeneralSettings
from src.frontend.stacked_windows.settings.global_management import (
    GlobalManagementSettings,
)
from src.frontend.stacked_windows.settings.movies_management import (
    MoviesManagementSettings,
)
from src.frontend.stacked_windows.settings.plugins import PluginsSettings
from src.frontend.stacked_windows.settings.screenshots import ScreenShotSettings
from src.frontend.stacked_windows.settings.series_management import (
    SeriesManagementSettings,
)
from src.frontend.stacked_windows.settings.templates import TemplatesSettings
from src.frontend.stacked_windows.settings.trackers import TrackersSettings
from src.frontend.stacked_windows.settings.user_tokens import UserTokenSettings

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class Settings(QWidget):
    re_load_settings = Signal()

    def __init__(self, config: ConfigManager, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.setObjectName("settingsWindow")

        self.config = config
        self.main_window = parent
        self._enable_plugins_before_apply = config.settings.general.enable_plugins
        self.re_load_settings.connect(self._reload_settings)
        GSigs().settings_refresh.connect(self._reload_settings)
        GSigs().settings_swap_tab.connect(self._swap_tab)

        self._save_approved_counter = 0

        self.general_settings_content = GeneralSettings(
            self.config, self.main_window, self
        )
        self.plugins_settings_content = PluginsSettings(
            self.config, self.main_window, self
        )
        self.movies_settings_content = MoviesManagementSettings(
            self.config, self.main_window, self
        )
        self.series_settings_content = SeriesManagementSettings(
            self.config, self.main_window, self
        )
        self.global_settings_content = GlobalManagementSettings(
            self.config, self.main_window, self
        )
        self.template_settings_content = TemplatesSettings(
            self.config, self.main_window, self
        )
        self.user_token_settings_content = UserTokenSettings(
            self.config, self.main_window, self
        )
        self.clients_settings_content = ClientsSettings(
            self.config, self.main_window, self
        )
        self.trackers_settings_content = TrackersSettings(
            self.config, self.main_window, self
        )
        self.screenshots_settings_content = ScreenShotSettings(
            self.config, self.main_window, self
        )
        self.dependencies_settings_content = DependencySettings(
            self.config, self.main_window, self
        )
        self.about_content = AboutTab(self.config, self.main_window, self)

        self.settings_map: dict[SettingsTabs, BaseSettings] = {
            SettingsTabs.GENERAL_SETTINGS: self.general_settings_content,
            SettingsTabs.PLUGINS_SETTINGS: self.plugins_settings_content,
            SettingsTabs.MOVIES_SETTINGS: self.movies_settings_content,
            SettingsTabs.SERIES_SETTINGS: self.series_settings_content,
            SettingsTabs.GLOBAL_SETTINGS: self.global_settings_content,
            SettingsTabs.TEMPLATES_SETTINGS: self.template_settings_content,
            SettingsTabs.USER_TOKENS_SETTINGS: self.user_token_settings_content,
            SettingsTabs.CLIENTS_SETTINGS: self.clients_settings_content,
            SettingsTabs.TRACKERS_SETTINGS: self.trackers_settings_content,
            SettingsTabs.SCREENSHOTS_SETTINGS: self.screenshots_settings_content,
            SettingsTabs.DEPENDENCIES_SETTINGS: self.dependencies_settings_content,
            SettingsTabs.ABOUT_TAB: self.about_content,
        }

        for widget in self.settings_map.values():
            widget.updated_settings_applied.connect(
                self._update_applied_settings_counter
            )

        self.tab_widget = QTabWidget()
        self.tab_widget.currentChanged.connect(GSigs().settings_tab_changed.emit)
        self.tab_widget.addTab(self.general_settings_content, "General")
        self.tab_widget.addTab(self.plugins_settings_content, "Plugins")
        self.tab_widget.addTab(self.movies_settings_content, "Movies Management")
        self.tab_widget.addTab(self.series_settings_content, "Series Management")
        self.tab_widget.addTab(self.global_settings_content, "Global Management")
        self.tab_widget.addTab(self.template_settings_content, "Templates")
        self.tab_widget.addTab(self.user_token_settings_content, "User Tokens")
        self.tab_widget.addTab(self.clients_settings_content, "Clients")
        self.tab_widget.addTab(self.trackers_settings_content, "Trackers")
        self.tab_widget.addTab(self.screenshots_settings_content, "Screenshots")
        self.tab_widget.addTab(self.dependencies_settings_content, "Dependencies")
        self.tab_widget.addTab(self.about_content, "About")

        self.cancel_settings = QPushButton("Cancel")
        self.cancel_settings.setToolTip("Cancel changes and close settings")
        self.cancel_settings.clicked.connect(self._cancel_settings)

        self.save_as_new_config = QPushButton("Save As")
        self.save_as_new_config.setToolTip("Save as new configuration")
        self.save_as_new_config.clicked.connect(self._save_new_config)

        self.apply_settings = QPushButton("Apply")
        self.apply_settings.setToolTip("Apply changes and close settings")
        self.apply_settings.clicked.connect(self._apply_settings)

        settings_lower_layout = QHBoxLayout()
        settings_lower_layout.setContentsMargins(0, 0, 0, 0)
        settings_lower_layout.addWidget(self.cancel_settings)
        settings_lower_layout.addSpacerItem(
            QSpacerItem(
                20, 40, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
        )
        settings_lower_layout.addWidget(self.save_as_new_config)
        settings_lower_layout.addWidget(self.apply_settings)

        right_layout_box = QVBoxLayout()
        right_layout_box.addWidget(self.tab_widget, stretch=10)
        right_layout_box.addLayout(settings_lower_layout, stretch=1)

        layout = QVBoxLayout(self)
        layout.addLayout(right_layout_box)

    @Slot(object)
    def _swap_tab(self, tab: SettingsTabs) -> None:
        self.tab_widget.setCurrentWidget(self.settings_map[tab])

    def _cancel_settings(self) -> None:
        self._reload_settings()
        GSigs().settings_close.emit()

    def _save_new_config(self) -> None:
        save_cfg_path, _ = QFileDialog.getSaveFileName(
            parent=self,
            caption="Save Config As",
            filter="*.toml",
            dir=str(self.config.paths.user_configs),
        )
        if save_cfg_path:
            self.config.save_as(Path(save_cfg_path))
            self.general_settings_content.load_selected_configs()
            self._apply_settings()

    def _apply_settings(self) -> None:
        if not self._pending_screenshot_dependencies_are_valid():
            return

        self._save_approved_counter = 0
        self._enable_plugins_before_apply = self.config.settings.general.enable_plugins
        self.general_settings_content.update_saved_settings.emit()
        self.plugins_settings_content.update_saved_settings.emit()
        self.movies_settings_content.update_saved_settings.emit()
        self.series_settings_content.update_saved_settings.emit()
        self.global_settings_content.update_saved_settings.emit()
        self.template_settings_content.update_saved_settings.emit()
        self.user_token_settings_content.update_saved_settings.emit()
        self.clients_settings_content.update_saved_settings.emit()
        self.trackers_settings_content.update_saved_settings.emit()
        self.screenshots_settings_content.update_saved_settings.emit()
        self.dependencies_settings_content.update_saved_settings.emit()
        self.about_content.update_saved_settings.emit()

    def _pending_screenshot_dependencies_are_valid(self) -> bool:
        screenshots = self.screenshots_settings_content
        if not screenshots.ss_enabled_btn.isChecked():
            return True

        dependencies = self.dependencies_settings_content
        unavailable = unavailable_screenshot_dependency(
            screenshots.ss_mode_combo.currentData(),
            dependencies.pending_ffmpeg_path,
            dependencies.pending_frame_forge_path,
        )
        if unavailable is None:
            return True

        requirement = (
            "basic and simple comparison screenshots"
            if unavailable is Dependencies.FFMPEG
            else "advanced comparison screenshots"
        )
        QMessageBox.critical(
            self,
            "Dependency Error",
            (
                f"{unavailable} isn't detected and is required for {requirement}."
                "\n\nChoose a valid executable in Dependencies before applying "
                "these settings."
            ),
        )
        self.tab_widget.setCurrentWidget(self.dependencies_settings_content)
        return False

    @Slot()
    def _update_applied_settings_counter(self) -> None:
        self._save_approved_counter += 1
        if self._save_approved_counter == len(self.settings_map):
            self._save_all_settings()

    def _save_all_settings(self) -> None:
        self._save_approved_counter = 0
        self.config.save()
        plugins_toggled = (
            self.config.settings.general.enable_plugins
            != self._enable_plugins_before_apply
        )
        GSigs().settings_close.emit()
        self._reload_settings()
        if plugins_toggled:
            self._prompt_restart_for_plugins()

    def _prompt_restart_for_plugins(self) -> None:
        response = QMessageBox.question(
            self,
            "Restart Required",
            "External plugins were enabled or disabled. NfoForge must be "
            "restarted for this change to take effect. Restart now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response == QMessageBox.StandardButton.Yes:
            restart_application(self.main_window)

    def _reload_settings(self) -> None:
        self._save_approved_counter = 0
        self.general_settings_content.load_saved_settings.emit()
        self.plugins_settings_content.load_saved_settings.emit()
        self.movies_settings_content.load_saved_settings.emit()
        self.series_settings_content.load_saved_settings.emit()
        self.global_settings_content.load_saved_settings.emit()
        self.template_settings_content.load_saved_settings.emit()
        self.user_token_settings_content.load_saved_settings.emit()
        self.clients_settings_content.load_saved_settings.emit()
        self.trackers_settings_content.load_saved_settings.emit()
        self.screenshots_settings_content.load_saved_settings.emit()
        self.dependencies_settings_content.load_saved_settings.emit()
