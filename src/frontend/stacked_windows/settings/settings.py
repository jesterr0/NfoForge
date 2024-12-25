from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QWidget,
    QSizePolicy,
    QVBoxLayout,
    QSpacerItem,
    QTabWidget,
    QPushButton,
    QFileDialog,
)

from src.config.config import Config
from src.enums.settings_window import SettingsTabs
from src.frontend.stacked_windows.settings.base import BaseSettings
from src.frontend.stacked_windows.settings.general import GeneralSettings
from src.frontend.stacked_windows.settings.movies import MoviesSettings

# from src.frontend.stacked_windows.settings.series import SeriesSettings
from src.frontend.stacked_windows.settings.templates import TemplatesSettings
from src.frontend.stacked_windows.settings.security import SecuritySettings
from src.frontend.stacked_windows.settings.clients import ClientsSettings
from src.frontend.stacked_windows.settings.trackers import TrackersSettings
from src.frontend.stacked_windows.settings.screenshots import ScreenShotSettings
from src.frontend.stacked_windows.settings.dependencies import DependencySettings
from src.frontend.stacked_windows.settings.about import AboutTab

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class Settings(QWidget):
    close_settings = Signal()
    re_load_settings = Signal()
    swap_tab = Signal(object)

    def __init__(self, config: Config, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.setObjectName("settingsWindow")

        self.config = config
        self.main_window = parent
        self.re_load_settings.connect(self._reload_settings)
        self.swap_tab.connect(self._swap_tab)

        self._save_approved_counter = 0

        self.general_settings_content = GeneralSettings(
            self.config, self.main_window, self
        )
        self.movies_settings_content = MoviesSettings(
            self.config, self.main_window, self
        )
        # self.series_settings_content = SeriesSettings()
        self.template_settings_content = TemplatesSettings(
            self.config, self.main_window, self
        )
        self.security_settings_content = SecuritySettings(
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
            SettingsTabs.MOVIES_SETTINGS: self.movies_settings_content,
            # SettingsTabs.SERIES_SETTINGS: self.series_settings_content,
            SettingsTabs.TEMPLATES_SETTINGS: self.template_settings_content,
            SettingsTabs.SECURITY_SETTINGS: self.security_settings_content,
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
        self.tab_widget.addTab(self.general_settings_content, "General")
        self.tab_widget.addTab(self.movies_settings_content, "Movies")
        # self.tab_widget.addTab(self.series_settings_content, "Series")
        self.tab_widget.addTab(self.template_settings_content, "Templates")
        self.tab_widget.addTab(self.security_settings_content, "Security")
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
                20, 40, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
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
    def _swap_tab(self, tab: SettingsTabs):
        self.tab_widget.setCurrentWidget(self.settings_map[tab])

    def _cancel_settings(self) -> None:
        self._reload_settings()
        self.close_settings.emit()

    def _save_new_config(self) -> None:
        save_cfg, _ = QFileDialog.getSaveFileName(
            parent=self,
            caption="Save Config As",
            filter="*.toml",
            dir=str(self.config.USER_CONFIG_DIR),
        )
        if save_cfg:
            save_cfg = Path(save_cfg)
            self.config.program_conf.current_config = save_cfg.stem
            self.config.save_config(save_cfg)
            self.general_settings_content.load_selected_configs()
            self._apply_settings()

    def _apply_settings(self) -> None:
        self._save_approved_counter = 0
        self.general_settings_content.update_saved_settings.emit()
        self.movies_settings_content.update_saved_settings.emit()
        self.template_settings_content.update_saved_settings.emit()
        self.security_settings_content.update_saved_settings.emit()
        self.clients_settings_content.update_saved_settings.emit()
        self.trackers_settings_content.update_saved_settings.emit()
        self.screenshots_settings_content.update_saved_settings.emit()
        self.dependencies_settings_content.update_saved_settings.emit()

    @Slot()
    def _update_applied_settings_counter(self) -> None:
        self._save_approved_counter += 1
        if self._save_approved_counter == len(self.settings_map):
            self._save_all_settings()

    def _save_all_settings(self) -> None:
        self._save_approved_counter = 0
        self.config.save_config()
        self.close_settings.emit()
        self._reload_settings()

    def _reload_settings(self) -> None:
        self._save_approved_counter = 0
        self.general_settings_content.load_saved_settings.emit()
        self.movies_settings_content.load_saved_settings.emit()
        self.template_settings_content.load_saved_settings.emit()
        self.security_settings_content.load_saved_settings.emit()
        self.clients_settings_content.load_saved_settings.emit()
        self.trackers_settings_content.load_saved_settings.emit()
        self.screenshots_settings_content.load_saved_settings.emit()
        self.dependencies_settings_content.load_saved_settings.emit()
