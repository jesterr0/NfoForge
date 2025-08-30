from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox, QVBoxLayout

from src.config.config import Config
from src.frontend.custom_widgets.series_episode_mapper import SeriesEpisodeMapper
from src.frontend.wizards.wizard_base_page import BaseWizardPage

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class SeriesMatch(BaseWizardPage):
    def __init__(self, config: Config, parent: "MainWindow"):
        super().__init__(config, parent)
        self.setTitle("Series Match")
        self.setObjectName("seriesMatch")
        self.setCommitPage(True)

        self.main_window = parent

        self.series_mapper = SeriesEpisodeMapper(parent=self)

        layout = QVBoxLayout(self)
        layout.addWidget(self.series_mapper)

    def initializePage(self):
        """Initialize the page and load data into the series mapper"""
        # load data into the series mapper
        if self.config.media_input_payload and self.config.media_search_payload:
            self.series_mapper.load_data(
                self.config.media_input_payload, self.config.media_search_payload
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
            self.config.media_input_payload.series_episode_map = episode_maps

        super().validatePage()
        return True

    def reset_page(self):
        """Reset the page data"""
        self.series_mapper.clear_data()
