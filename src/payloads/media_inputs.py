from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pymediainfo import MediaInfo

from src.enums.media_type import MediaType
from src.enums.series import EpisodeFormat
from src.packages.custom_types import ComparisonPair


@dataclass(slots=True)
class MediaInputPayload:
    # original user selection (file or dir)
    input_path: Path | None = None
    # updated in MediaSearch after the input page
    media_type: MediaType | None = None
    working_dir: Path | None = None
    file_list: list[Path] = field(default_factory=list)  # all relevant files found
    file_list_mediainfo: dict[Path, MediaInfo] = field(default_factory=dict)
    # maps original file input to renamed output
    file_list_rename_map: dict[Path, Path] = field(default_factory=dict)
    comparison_pair: ComparisonPair | None = None

    # series stuff
    series_episode_map: dict[Path, dict[str, Any]] | None = None
    series_episode_format: EpisodeFormat = EpisodeFormat.STANDARD

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

    def apply_rename_mapping(
        self,
        rename_mapping: dict[Path, Path],
        updated_input_path: Path | None = None,
    ) -> None:
        """Re-point every path this payload holds at its renamed location.

        Called after the renames have been executed on disk. Every field keyed
        by (or holding) an input path has to move together, otherwise later
        pages look up a path that no longer exists, e.g. the screenshots page
        resolving `comparison_pair.media` against `file_list_mediainfo`.

        Args:
            rename_mapping: Map of old path -> new path for renamed files.
            updated_input_path: New input path, when the rename moved it.
        """
        if not rename_mapping:
            return

        for i, old_path in enumerate(self.file_list):
            if old_path in rename_mapping:
                self.file_list[i] = rename_mapping[old_path]

        if self.file_list_mediainfo:
            self.file_list_mediainfo = {
                rename_mapping.get(old_path, old_path): mi_obj
                for old_path, mi_obj in self.file_list_mediainfo.items()
            }

        if self.series_episode_map:
            self.series_episode_map = {
                rename_mapping.get(old_path, old_path): ep_data
                for old_path, ep_data in self.series_episode_map.items()
            }

        # the comparison media is one of the renamed files; the source usually
        # sits outside the rename set but still moves when its folder is renamed
        if self.comparison_pair:
            self.comparison_pair = self.comparison_pair._replace(
                source=rename_mapping.get(
                    self.comparison_pair.source, self.comparison_pair.source
                ),
                media=rename_mapping.get(
                    self.comparison_pair.media, self.comparison_pair.media
                ),
            )

        if updated_input_path:
            self.input_path = updated_input_path

        # renames are complete
        self.file_list_rename_map.clear()

    def reset(self, input_path: Path | None = None) -> None:
        """Reset all fields to initial state."""
        self.input_path = input_path
        self.media_type = None
        self.working_dir = None
        self.file_list.clear()
        self.file_list_mediainfo.clear()
        self.file_list_rename_map.clear()
        self.comparison_pair = None
        self.series_episode_map = None
        self.series_episode_format = EpisodeFormat.STANDARD
