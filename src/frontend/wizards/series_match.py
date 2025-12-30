from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox, QVBoxLayout

from src.config.config import Config
from src.context.processing_context import ProcessingContext
from src.frontend.custom_widgets.series_episode_mapper import SeriesEpisodeMapper
from src.frontend.wizards.wizard_base_page import BaseWizardPage

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class SeriesMatch(BaseWizardPage):
    def __init__(
        self, config: Config, context: ProcessingContext, parent: "MainWindow"
    ) -> None:
        super().__init__(config, context, parent)
        self.setTitle("Series Match")
        self.setObjectName("seriesMatch")
        self.setCommitPage(True)

        self.main_window = parent

        self.series_mapper = SeriesEpisodeMapper(parent=self)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addWidget(self.series_mapper)

    def initializePage(self):
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
                "Please ensure all files are properly mapped to episodes before continuing.",
            )
            return False

        # store the episode mappings in config for later use
        episode_maps = self.series_mapper.get_episode_map()
        if episode_maps:
            self.context.media_input.series_episode_map = episode_maps

        super().validatePage()
        return True
