from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox, QVBoxLayout

from src.backend.trackers.media_support import UNSUPPORTED_SERIES_TRACKERS
from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.frontend.custom_widgets.tracker_settings import TrackerSettingsWidget
from src.frontend.global_signals import GSigs
from src.frontend.wizards.wizard_base_page import BaseWizardPage

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class TrackersPage(BaseWizardPage):
    def __init__(
        self, config: ConfigManager, context: ProcessingContext, parent: "MainWindow"
    ) -> None:
        super().__init__(config, context, parent)

        self.setObjectName("trackerPage")
        self.setTitle("Trackers")
        self.setCommitPage(True)

        self.config = config
        self.main_window = parent

        self.tracker_selection = TrackerSettingsWidget(self.config, parent=self)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tracker_selection)

    def initializePage(self) -> None:
        unsupported_trackers = (
            UNSUPPORTED_SERIES_TRACKERS
            if self.context.media_input.media_type is MediaType.SERIES
            else None
        )
        self.tracker_selection.load_from_config(
            unsupported_trackers=unsupported_trackers,
        )

    def validatePage(self) -> bool:
        trackers = self.tracker_selection.get_selected_trackers()
        if not trackers:
            QMessageBox.information(
                self, "Warning", "You must select at least one tracker"
            )
            return False

        self.context.shared_data.selected_trackers = trackers

        self.tracker_selection.save_editor_settings()
        self.config.settings.trackers.order = self.tracker_selection.current_order()

        self.config.save()
        GSigs().settings_refresh.emit()
        super().validatePage()
        return True
