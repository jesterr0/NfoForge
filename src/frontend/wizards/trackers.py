from collections.abc import Sequence
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox, QVBoxLayout

from src.backend.trackers.media_support import (
    UNIT3D_TRACKERS,
    UNSUPPORTED_SERIES_TRACKERS,
)
from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.frontend.custom_widgets.tracker_settings import TrackerSettingsWidget
from src.frontend.global_signals import GSigs
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.payloads.series import (
    build_series_release_info,
    describe_multi_season_pack,
)

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

    def _resuming_job(self) -> bool:
        """Whether this run came from a saved job rather than the full wizard.

        A resumed run's tracker choice is scoped to that run: it starts from
        what the job carried, cannot touch trackers the job already uploaded
        to, and must not rewrite the profile's enabled flags on its way through.
        """
        return self.context.loaded_job_path is not None

    def initializePage(self) -> None:
        unsupported_trackers = (
            UNSUPPORTED_SERIES_TRACKERS
            if self.context.media_input.media_type is MediaType.SERIES
            else None
        )
        resuming = self._resuming_job()
        self.tracker_selection.load_from_config(
            unsupported_trackers=unsupported_trackers,
            locked_trackers=(
                self.context.loaded_uploaded_trackers
                | self.context.loaded_uncertain_trackers
            )
            if resuming
            else None,
            preselected=self.context.shared_data.selected_trackers
            if resuming
            else None,
            persist_enabled=not resuming,
        )

    def validatePage(self) -> bool:
        trackers = self.tracker_selection.get_selected_trackers()
        if not trackers:
            # Say why the greyed-out rows are unavailable. Every compatible
            # tracker being locked is a real outcome for an archive that has
            # already been everywhere, and without this the page just refuses.
            locked = (
                self.context.loaded_uploaded_trackers
                | self.context.loaded_uncertain_trackers
            )
            message = "You must select at least one tracker"
            if self._resuming_job() and locked:
                message += (
                    ".\n\nGreyed-out trackers already have this release, or their "
                    "upload result is still unresolved. Resolve those from the "
                    "Jobs dialog, or use 'Start Over' to leave this job."
                )
            QMessageBox.information(self, "Warning", message)
            return False

        if not self._confirm_multi_season_pack(trackers):
            return False

        self.context.shared_data.selected_trackers = trackers

        self.tracker_selection.save_editor_settings()
        self.config.settings.trackers.order = self.tracker_selection.current_order()

        self.config.save()
        GSigs().settings_refresh.emit()
        super().validatePage()
        return True

    def _confirm_multi_season_pack(self, trackers: Sequence[TrackerSelection]) -> bool:
        """Ask before filing a multi-season pack under one season.

        This is the last page where the choice is still the user's -- past it
        the release name says "S01-S05" everywhere while the tracker's own
        record says a single season, and nothing surfaces the difference.
        Asked once per visit, and only when a UNIT3D tracker is actually
        selected, so a single-season release never sees it.
        """
        if not any(tracker in UNIT3D_TRACKERS for tracker in trackers):
            return True
        message = describe_multi_season_pack(
            build_series_release_info(self.context.media_input)
        )
        if not message:
            return True
        return (
            QMessageBox.warning(
                self,
                "Multi-Season Pack",
                message,
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Ok
        )
