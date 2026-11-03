from collections.abc import Sequence
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox, QVBoxLayout

from nfoforge.config.config import ConfigManager
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.frontend.custom_widgets.series_episode_mapper import SeriesEpisodeMapper
from nfoforge.frontend.wizards.wizard_base_page import BaseWizardPage
from nfoforge.payloads.series import (
    build_series_release_info,
    describe_missing_upload_fields,
)

if TYPE_CHECKING:
    from nfoforge.frontend.windows.main_window import MainWindow


_MAX_LISTED_FILES = 8


def _bullet_list(names: Sequence[str]) -> str:
    """Render at most ``_MAX_LISTED_FILES`` names, counting any remainder."""
    shown = [f"  • {name}" for name in names[:_MAX_LISTED_FILES]]
    remaining = len(names) - _MAX_LISTED_FILES
    if remaining > 0:
        shown.append(f"  • ...and {remaining} more")
    return "\n".join(shown)


def _incomplete_mapping_message(series_mapper: SeriesEpisodeMapper) -> str:
    """Explain why a series episode mapping was refused, naming the files.

    Three different situations reach this: TVDB returned no episode data at
    all, some files carry no season/episode, and two files claim the same
    episode. They used to share one sentence -- "Please ensure all files are
    properly mapped to episodes before continuing" -- which named nothing. On
    an overlap that sentence is actively misleading, because every row on
    screen is filled in and looks mapped; the user is told to finish work
    that is already done, with no way to tell which rows collide.
    """
    if series_mapper.has_unmapped_files() and not series_mapper.has_tvdb_episode_data():
        return (
            "TVDB returned no episode data for this series, so files could not "
            "be auto-matched. Enter a season and episode number for each file "
            "manually before continuing."
        )

    problems: list[str] = []

    unmapped = series_mapper.unmapped_files()
    if unmapped:
        problems.append(
            f"{len(unmapped)} file(s) have no season and episode number:\n"
            + _bullet_list([path.name for path in unmapped])
        )

    overlaps = series_mapper.overlapping_claims()
    if overlaps:
        lines: list[str] = []
        for (season, episode), files in overlaps:
            where = (
                f"S{season:02d}E{episode:02d}"
                if isinstance(season, int) and isinstance(episode, int)
                else f"season {season}, episode {episode}"
            )
            lines.append(f"  • {where} is claimed by:")
            lines.extend(f"      - {path.name}" for path in files)
        problems.append(
            "The same episode is claimed by more than one file:\n"
            + "\n".join(lines)
            + "\n\nA file covering several episodes should claim all of them; "
            "give every other file its own episode."
        )

    if not problems:
        return (
            "Please ensure all files are properly mapped to episodes before continuing."
        )

    return "\n\n".join(problems)


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
            self.series_mapper.focus_first_problem()
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
