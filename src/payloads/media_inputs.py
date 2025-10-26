from dataclasses import dataclass, field
from pathlib import Path

from pymediainfo import MediaInfo

from src.enums.media_type import MediaType
from src.packages.custom_types import ComparisonPair


@dataclass(slots=True)
class MediaInputPayload:
    # original user selection (file or dir)
    input_path: Path | None = None
    # updated in MediaSearch after the input page
    media_type: MediaType | None = None
    working_dir: Path | None = None
    file_list: list[Path] = field(default_factory=list)  # All relevant files found
    file_list_mediainfo: dict[Path, MediaInfo] = field(default_factory=dict)
    # maps original file input to renamed output
    file_list_rename_map: dict[Path, Path] = field(default_factory=dict)

    # TODO: need to work this into the program
    comparison_pair: ComparisonPair | None = None
    series_episode_map: dict[Path, dict] | None = None

    def has_basic_data(self) -> bool:
        """Check if essential data is present."""
        return bool(self.input_path and self.file_list and self.file_list_mediainfo)

    def require_input_path(self) -> Path:
        """Require input path and return it."""
        if not self.input_path:
            raise RuntimeError("'input_path' has not been defined")
        return self.input_path

    def require_media_type(self) -> MediaType:
        """Require media type and return it."""
        if not self.media_type:
            raise RuntimeError("'media_type' has not been defined")
        return self.media_type

    def require_working_dir(self) -> Path:
        """Ensure working directory is set."""
        if not self.working_dir:
            raise RuntimeError("Working directory not set")
        return self.working_dir

    def get_first_file(self, raise_error: bool = False) -> Path | None:
        """Get the first file from file_list.

        Returns None on any error or when no files are available.
        """
        try:
            if self.file_list:
                return self.file_list[0]
        except Exception:
            if raise_error:
                raise
        return None

    def require_first_file(self) -> Path:
        """Wraps `get_first_file` but requires the first file strictly to make it easier on static type checkers."""
        first = self.get_first_file(True)
        if not first:
            raise RuntimeError("No input file available")
        return first

    def get_mediainfo(self, fp: Path) -> MediaInfo | None:
        return self.file_list_mediainfo.get(fp)

    def require_mediainfo(self, fp: Path) -> MediaInfo:
        mi = self.get_mediainfo(fp)
        if not mi or (mi and not isinstance(mi, MediaInfo)):
            raise RuntimeError(f"Failed to get MediaInfo object for '{fp}'")
        return mi

    # Series support helpers (commented out for now, ready for future implementation)
    # def get_episode_info(self, path: Path) -> dict | None:
    #     """Get episode metadata for a specific file.
    #
    #     Args:
    #         path: Either an original path or a current renamed path
    #
    #     Returns:
    #         Episode metadata dict, or None if not found
    #     """
    #     if not self.series_episode_map:
    #         return None
    #
    #     # Try as original path first
    #     if path in self.series_episode_map:
    #         return self.series_episode_map[path]
    #
    #     # Try reverse lookup: maybe it's a renamed path
    #     original = self.get_original_path(path)
    #     return self.series_episode_map.get(original)
    #
    # def get_episodes_by_season(self, season: int) -> list[tuple[Path, dict]]:
    #     """Get all episodes for a specific season with their current paths.
    #
    #     Args:
    #         season: Season number
    #
    #     Returns:
    #         List of (current_path, episode_info) tuples
    #     """
    #     if not self.series_episode_map:
    #         return []
    #
    #     episodes = []
    #     for original_path, episode_info in self.series_episode_map.items():
    #         if episode_info.get('season') == season:
    #             current_path = self.get_current_path(original_path)
    #             episodes.append((current_path, episode_info))
    #
    #     return episodes

    def reset(self) -> None:
        self.input_path = None
        self.media_type = None
        self.working_dir = None
        self.file_list.clear()
        self.file_list_mediainfo.clear()
        self.file_list_rename_map.clear()
        self.comparison_pair = None
