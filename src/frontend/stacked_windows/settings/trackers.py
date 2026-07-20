from typing import TYPE_CHECKING

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QLabel

from src.config.config import ConfigManager
from src.enums.tracker_selection import TrackerSelection
from src.frontend.custom_widgets.sortable_listbox import SortableListBox
from src.frontend.custom_widgets.tracker_listbox import TrackerListWidget
from src.frontend.stacked_windows.settings.base import BaseSettings

if TYPE_CHECKING:
    from src.frontend.stacked_windows.settings.settings import Settings
    from src.frontend.windows.main_window import MainWindow


class TrackersSettings(BaseSettings):
    def __init__(
        self, config: ConfigManager, main_window: "MainWindow", parent: "Settings"
    ) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("trackersSettings")

        self.tracker_widget = TrackerListWidget(self.config, self)
        self.tracker_widget.setMinimumHeight(350)

        tracker_order_lbl = QLabel(
            "During processing the order below will be prioritized", self
        )
        self.tracker_order = SortableListBox(self)
        self.tracker_order.main_layout.setContentsMargins(0, 0, 0, 0)
        self.tracker_order.setMinimumHeight(130)

        self.add_widget(self.tracker_widget, stretch=5)
        self.add_widget(tracker_order_lbl)
        self.add_widget(self.tracker_order, stretch=2, add_stretch=True)

        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)

        self._load_saved_settings()

    @Slot()
    def _load_saved_settings(self) -> None:
        """Applies user saved settings from the config"""
        self.tracker_widget.add_items(self.config.settings.trackers.by_selection())
        self.tracker_order.load_items(
            [str(x) for x in self.config.settings.trackers.order]
        )

    @Slot()
    def _save_settings(self) -> None:
        self.tracker_widget.save_tracker_info()
        self.config.settings.trackers.order = [
            TrackerSelection(x) for x in self.tracker_order.get_items()
        ]
        self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self._load_saved_settings()
