from PySide6.QtCore import Slot

from src.frontend.stacked_windows.settings.base import BaseSettings
from src.frontend.custom_widgets.tracker_listbox import TrackerListWidget


class TrackersSettings(BaseSettings):
    def __init__(self, config, main_window, parent) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("trackersSettings")

        self.tracker_widget = TrackerListWidget(self.config, self)
        self.inner_layout.removeItem(self._spacer_item)
        self.inner_layout.addWidget(self.tracker_widget, stretch=1)

        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)

        self._load_saved_settings()

    @Slot()
    def _load_saved_settings(self) -> None:
        """Applies user saved settings from the config"""
        self.tracker_widget.add_items(self.config.tracker_map)

    @Slot()
    def _save_settings(self) -> None:
        self.tracker_widget.save_tracker_info()
        self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self._load_saved_settings()
