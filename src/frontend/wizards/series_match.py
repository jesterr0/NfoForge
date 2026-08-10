from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox, QVBoxLayout

from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.frontend.custom_widgets.series_episode_mapper import SeriesEpisodeMapper
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.payloads.series import (
    build_series_release_info,
    describe_missing_upload_fields,
)

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


def _incomplete_mapping_message(series_mapper: SeriesEpisodeMapper) -> str:
    """Choose the warning text for an incomplete series episode mapping.

    Distinguishes the "TVDB has no episode data for this series" case (the
    user needs to enter season/episode numbers manually) from the plain
    "some files still aren't mapped" case (the user just needs to finish
    mapping the remaining files).
    """
    if series_mapper.has_unmapped_files() and not series_mapper.has_tvdb_episode_data():
        return (
            "TVDB returned no episode data for this series, so files could not "
            "be auto-matched. Enter a season and episode number for each file "
            "manually before continuing."
        )
    return "Please ensure all files are properly mapped to episodes before continuing."


class SeriesMatch(BaseWizardPage):
    def __init__(
        self, config: ConfigManager, context: ProcessingContext, parent: "MainWindow"
    ) -> None:
        super().__init__(config, context, parent)
        self.setTitle("Series Match")
        self.setObjectName("seriesMatch")
        self.setCommitPage(True)

        self.main_window = parent

        self.series_mapper = SeriesEpisodeMapper(parent=self)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addWidget(self.series_mapper)

    def initializePage(self) -> None:
        """Initialize the page and load data into the series mapper"""
        # load data into the series mapper
        if self.context.media_input and self.context.media_search:
            self.series_mapper.load_data(
                self.context.media_input, self.context.media_search
            )

    def validatePage(self) -> bool:
        """Validate the page and ensure mappings are complete"""
        # check if series mapper has valid mappings
        if not self.series_mapper.is_valid():
            QMessageBox.warning(
                self,
                "Incomplete Mapping",
                _incomplete_mapping_message(self.series_mapper),
            )
            return False

        # store the episode mappings in config for later use
        episode_maps = self.series_mapper.get_episode_map()
        if episode_maps:
            self.context.media_input.series_episode_map = episode_maps
        # update config with the selected episode format
        self.context.media_input.series_episode_format = (
            self.series_mapper.get_series_format()
        )

        # is_valid() above only proves every file has *a* mapping -- a mapping
        # whose episode (or season) is None still passes it. Resolve the
        # release the same way the uploader will, so a gap the filename-parsing
        # fallback can't cover (absolute-numbered anime, date-based episodes)
        # is caught here with the mapper still on screen, rather than being
        # silently dropped from the tracker payload much later.
        missing_message = describe_missing_upload_fields(
            build_series_release_info(self.context.media_input)
        )
        if missing_message:
            QMessageBox.warning(self, "Missing Season/Episode Numbers", missing_message)
            return False

        super().validatePage()
        return True
