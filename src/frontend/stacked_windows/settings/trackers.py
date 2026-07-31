import copy
from dataclasses import fields
from typing import TYPE_CHECKING

from PySide6.QtCore import Slot

from src.config.config import ConfigManager
from src.config.models import TrackerSettings
from src.frontend.custom_widgets.tracker_settings import TrackerSettingsWidget
from src.frontend.stacked_windows.settings.base import BaseSettings

if TYPE_CHECKING:
    from src.frontend.stacked_windows.settings.settings import Settings
    from src.frontend.windows.main_window import MainWindow


class TrackersSettings(BaseSettings):
    """Transactional settings wrapper around the shared tracker editor."""

    def __init__(
        self, config: ConfigManager, main_window: "MainWindow", parent: "Settings"
    ) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("trackersSettings")

        self._working_config = self._copy_config_with_trackers(
            self.config.settings.trackers
        )
        self._defaults_config = self._copy_config_with_trackers(
            self.config.defaults.trackers
        )
        self._baseline_trackers = copy.deepcopy(self.config.settings.trackers)

        self.tracker_widget = TrackerSettingsWidget(self._working_config, self)

        # Keep these aliases for consumers that inspect the settings page while
        # the actual UI now lives in the shared widget used by the wizard too.
        self.tracker_list = self.tracker_widget.tracker_list
        self.tracker_stack = self.tracker_widget.tracker_stack
        self.tracker_splitter = self.tracker_widget.tracker_splitter
        self._editor_map = self.tracker_widget._editor_map

        self.add_widget(self.tracker_widget, stretch=1, add_stretch=True)

        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)

        self._load_saved_settings()

    def _copy_config_with_trackers(
        self,
        tracker_settings: TrackerSettings,
    ) -> ConfigManager:
        """Return a lightweight config copy whose tracker payloads are isolated."""
        copied_config = copy.copy(self.config)
        copied_config.settings = copy.copy(self.config.settings)
        copied_config.settings.trackers = copy.deepcopy(tracker_settings)
        return copied_config

    @Slot()
    def _load_saved_settings(self) -> None:
        """Reload the live configuration into the page's working controls."""
        self._working_config.settings.trackers = copy.deepcopy(
            self.config.settings.trackers
        )
        self._baseline_trackers = copy.deepcopy(self.config.settings.trackers)
        self.tracker_widget.load_from_config(self._working_config)

    def _apply_working_tracker_changes(self) -> None:
        live_trackers = self.config.settings.trackers.by_selection()
        working_trackers = self._working_config.settings.trackers.by_selection()
        baseline_trackers = self._baseline_trackers.by_selection()

        # Only copy values changed by this page. This prevents tracker fields
        # owned by other settings pages from being overwritten by a stale
        # working snapshot when the whole Settings window is applied.
        for tracker, working_info in working_trackers.items():
            live_info = live_trackers[tracker]
            baseline_info = baseline_trackers[tracker]
            for field in fields(working_info):
                value = getattr(working_info, field.name)
                if value != getattr(baseline_info, field.name):
                    setattr(live_info, field.name, copy.deepcopy(value))

        self.config.settings.trackers.order = self.tracker_widget.current_order()

    @Slot()
    def _save_settings(self) -> None:
        self.tracker_widget.save_editor_settings()
        self._apply_working_tracker_changes()
        self.updated_settings_applied.emit()

    def _current_order(self):
        return self.tracker_widget.current_order()

    def apply_defaults(self) -> None:
        """Load tracker defaults into the controls without saving immediately."""
        self._working_config.settings.trackers = copy.deepcopy(
            self.config.settings.trackers
        )
        self.tracker_widget.load_from_config(self._defaults_config)
