from dataclasses import dataclass


@dataclass
class EpisodeSelection:
    """Data structure for episode selection in series renaming."""

    # series information
    series_title: str
    series_year: int | None = None
    tvdb_id: str | None = None
    imdb_id: str | None = None

    # season information
    season_number: int = 1

    # episode information
    episode_number: int = 1
    episode_title: str | None = None
    episode_air_date: str | None = None
    episode_absolute_number: int | None = None

    # multi-episode handling
    is_multi_episode: bool = False
    end_episode_number: int | None = None
    end_episode_title: str | None = None

    # numbering scheme
    numbering_scheme: str = "aired"  # aired, dvd, absolute

    # additional metadata
    episode_overview: str | None = None
    episode_runtime: int | None = None

    def get_episode_range_display(self) -> str:
        """Get a display string for episode range."""
        if self.is_multi_episode and self.end_episode_number:
            return f"E{self.episode_number:02d}-E{self.end_episode_number:02d}"
        return f"E{self.episode_number:02d}"

    def get_season_episode_display(self) -> str:
        """Get a display string for season and episode."""
        return f"S{self.season_number:02d}{self.get_episode_range_display()}"
