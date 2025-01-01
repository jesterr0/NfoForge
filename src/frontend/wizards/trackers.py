from collections.abc import Iterable
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

        confirm = self.confirm_trackers(trackers)
        if not confirm:
            QMessageBox.information(
                self,
                "Warning",
                "You must supply 'API Key' and 'Announce URL' for the selected tracker(s)",
            )
            return False

        self.config.shared_data.selected_trackers = trackers

        self.tracker_selection.save_tracker_info()

        self.config.save_config()
        return True

    def confirm_trackers(self, trackers: Iterable) -> bool:
        """
        Check that the minimum required inputs are supplied.
        At the moment this works for the supported trackers but it
        might need to be expanded on and handled differently as we
        add more trackers.
        """
        for item in trackers:
            tracker_item = self.config.tracker_map[item]
            if any(
                not value
                for value in (
                    # TODO: we'll need to add other checks potentially here?
                    # TODO: this is technically not needed, as it's in the announce URL, look into this further!
                    # tracker_item.api_key,
                    tracker_item.announce_url,
                )
            ):
                return False

        return True

    @Slot()
    def reset_page(self):
        self.tracker_selection.clear()
