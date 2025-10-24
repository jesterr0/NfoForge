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
    file_list: list[Path] = field(default_factory=list)  # All relevant files found
    file_list_mediainfo: dict[Path, MediaInfo] = field(default_factory=dict)
    # maps original file input to renamed output
    # TODO: is this how we wanna do this?
    file_list_rename_map: dict[Path, Path] = field(default_factory=dict)
    # primary_file: Path  # Representative file for initial analysis
    # primary_mediainfo: MediaInfo  # Quick analysis for navigation

    comparison_pair: ComparisonPair | None = (
        None  # TODO: need to work this into the program
    )
    series_episode_map: dict[Path, dict] | None = None

    # TODO: do away with all the individual inputs below
    # search for each one and remove it if it not needed etc!
    script_file: Path | None = None
    source_file: Path | None = None
    source_file_mi_obj: MediaInfo | None = None
    encode_file: Path | None = None
    encode_file_mi_obj: MediaInfo | None = None
    encode_file_dir: Path | None = None
    renamed_file: Path | None = None
    working_dir: Path | None = None

    def is_empty(self, raise_error: bool = False) -> bool:
        """Checks if input_path, file_list, or file_list_mediainfo is empty."""
        if not self.input_path or not self.file_list or not self.file_list_mediainfo:
            if raise_error:
                raise AttributeError(
                    "input_path, file_list, or file_list_mediainfo is empty"
                )
            return True
        return False
    
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

    def get_first_file(self, raise_error: bool = False) -> Path | None:
        """Attempts to get the first file if there is renames, otherwise falls back to the first file in the filelist.

        Returns None on any error or when no files are available.
        """
        try:
            if self.file_list_rename_map:
                return next(iter(self.file_list_rename_map.values()))
            elif self.file_list:
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
        """Gets loaded mediainfo from file_list_mediainfo."""
        return self.file_list_mediainfo.get(fp)

    def get_renamed_path(self, fp: Path) -> Path:
        """Gets renamed path from file_list_rename_map falling back to input path."""
        return self.file_list_rename_map.get(fp, fp)

    def reset(self) -> None:
        self.input_path = None
        self.file_list.clear()
        self.file_list_mediainfo.clear()
        self.file_list_rename_map.clear()
        self.media_type = None
        self.comparison_pair = None

        self.script_file = None
        self.source_file = None
        self.source_file_mi_obj = None
        self.encode_file = None
        self.encode_file_mi_obj = None
        self.encode_file_dir = None
        self.renamed_file = None
        self.working_dir = None
