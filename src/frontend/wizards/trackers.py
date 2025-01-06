from typing import TYPE_CHECKING

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QVBoxLayout, QMessageBox

from src.config.config import Config
from src.frontend.custom_widgets.tracker_listbox import TrackerListWidget
from src.frontend.wizards.wizard_base_page import BaseWizardPage

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class TrackersPage(BaseWizardPage):
    def __init__(self, config: Config, parent: "MainWindow") -> None:
        super().__init__(config, parent)

        self.setObjectName("trackerPage")
        self.setTitle("Trackers")
        self.setCommitPage(True)

        self.config = config
        self.main_window = parent

        self.tracker_selection = TrackerListWidget(self.config, parent=self)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tracker_selection)

    def initializePage(self) -> None:
        self.tracker_selection.add_items(self.config.tracker_map)

    def validatePage(self) -> bool:
        trackers = self.tracker_selection.get_selected_trackers()
        if not trackers:
            QMessageBox.information(
                self, "Warning", "You must select at least one tracker"
            )
            return False

        self.config.shared_data.selected_trackers = trackers

        self.tracker_selection.save_tracker_info()

        self.config.save_config()
        return True

    @Slot()
    def reset_page(self):
        self.tracker_selection.clear()
