from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pymediainfo import MediaInfo

from nfoforge.core.disc.model import Disc, DiscError
from nfoforge.core.disc.mount import MOUNTS, MountRegistry
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.series import EpisodeFormat
from nfoforge.packages.custom_types import ComparisonPair
from nfoforge.payloads.media_analysis_cache import MediaAnalysisCache


def _moved_tree(old_root: Path, new_root: Path) -> Callable[[Path], Path]:
    """A remap that moves paths under `old_root` to the same place under `new_root`."""

    def remap(path: Path) -> Path:
        if path == old_root:
            return new_root
        try:
            return new_root / path.relative_to(old_root)
        except ValueError:
            return path

    return remap


@dataclass(slots=True)
class MediaInputPayload:
    # original user selection (file or dir)
    input_path: Path | None = None
    # updated in MediaSearch after the input page
    media_type: MediaType | None = None
    working_dir: Path | None = None
    file_list: list[Path] = field(default_factory=list)  # all relevant files found
    file_list_mediainfo: dict[Path, MediaInfo] = field(default_factory=dict)
    # Persisted release facts used when a saved archive is processed after the
    # original paths have disappeared.  Paths remain useful lexical identifiers
    # (title parsing and MediaInfo cache keys), but these facts must not be
    # re-derived with ``Path.is_dir()``/``stat()`` in source-less mode.
    input_kind: str | None = None
    content_size: int | None = None
    comparison_pair: ComparisonPair | None = None

    # A full-disc release (Blu-ray / DVD folder). When set, `file_list` holds
    # only the disc's primary media file -- the one clip MediaInfo and
    # screenshots work on -- and the release is named after `input_path`, never
    # after that clip. A list, because a release can be a set of discs.
    discs: list[Disc] = field(default_factory=list)

    # series stuff
    series_episode_map: dict[Path, dict[str, Any]] | None = None
    series_episode_format: EpisodeFormat = EpisodeFormat.STANDARD

    # Derived facts are scoped to this payload so every renderer that sees the
    # same media input naturally shares them without passing a cache around.
    analysis_cache: MediaAnalysisCache = field(
        default_factory=MediaAnalysisCache,
        init=False,
        repr=False,
        compare=False,
    )

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

    def is_disc(self) -> bool:
        """Whether the release is a full disc rather than loose media files."""
        return bool(self.discs)

    def primary_media_file(self) -> Path | None:
        """The file that stands for the release where one file is needed.

        For a disc this is the selected playlist's main clip, not whichever
        clip happens to sort first.
        """
        if self.discs:
            return self.discs[0].primary_media_file()
        return self.get_first_file()

    def release_name_path(self) -> Path | None:
        """The path the release's name is read from.

        A disc's clips are called `00001.m2ts` or `VTS_01_1.VOB`; everything
        the name can say about the release is on the disc's folder.
        """
        if self.discs:
            return self.input_path
        return self.get_first_file() or self.input_path

    def release_name(self) -> str:
        """`release_name_path` as text, without a file's extension.

        A disc folder's name is kept whole: "Movie.2020.BluRay" has no
        extension. A disc image's `.iso` is one.
        """
        path = self.release_name_path()
        if not path:
            return ""
        if self.discs and not self.discs[0].is_image:
            return path.name
        return path.stem

    def mount_disc_images(self, mounts: MountRegistry | None = None) -> None:
        """Mount each disc image, again if need be, and follow it if it moved.

        A saved job, or an image unmounted for its rename, can come back
        under another drive letter or mount point.
        """
        registry = mounts or MOUNTS
        for disc in self.discs:
            if disc.image is None:
                continue
            old_root = disc.root
            new_root = registry.mount(disc.image)
            if new_root != old_root:
                self._remap_paths(_moved_tree(old_root, new_root))

    def unmount_disc_images(self, mounts: MountRegistry | None = None) -> None:
        """Release every disc image this release mounted (before renaming one)."""
        registry = mounts or MOUNTS
        for disc in self.discs:
            if disc.image is not None:
                registry.release(disc.image)

    def get_mediainfo(self, fp: Path) -> MediaInfo | None:
        return self.file_list_mediainfo.get(fp)

    def require_mediainfo(self, fp: Path) -> MediaInfo:
        mi = self.get_mediainfo(fp)
        if not mi or (mi and not isinstance(mi, MediaInfo)):
            raise RuntimeError(f"Failed to get MediaInfo object for '{fp}'")
        return mi

    def require_existing_media_paths(self, *, include_comparison: bool) -> None:
        """Require filesystem and MediaInfo paths needed by downstream work."""
        input_path = self.require_input_path()
        if not input_path.exists():
            raise FileNotFoundError(f"Media input no longer exists: {input_path}")
        # a disc image's clips only exist while it is mounted
        try:
            self.mount_disc_images()
        except DiscError as error:
            raise FileNotFoundError(str(error)) from error

        missing_files = [path for path in self.file_list if not path.is_file()]
        if missing_files:
            raise FileNotFoundError(
                "Media file(s) no longer exist: "
                + ", ".join(str(path) for path in missing_files)
            )

        missing_mediainfo = [
            path for path in self.file_list if path not in self.file_list_mediainfo
        ]
        if missing_mediainfo:
            raise RuntimeError(
                "MediaInfo is missing for: "
                + ", ".join(str(path) for path in missing_mediainfo)
            )

        if not include_comparison or not self.comparison_pair:
            return

        comparison_paths = (
            self.comparison_pair.source,
            self.comparison_pair.media,
        )
        missing_comparison = [path for path in comparison_paths if not path.is_file()]
        if missing_comparison:
            raise FileNotFoundError(
                "Comparison file(s) no longer exist: "
                + ", ".join(str(path) for path in missing_comparison)
            )

        missing_comparison_mediainfo = [
            path for path in comparison_paths if path not in self.file_list_mediainfo
        ]
        if missing_comparison_mediainfo:
            raise RuntimeError(
                "MediaInfo is missing for comparison file(s): "
                + ", ".join(str(path) for path in missing_comparison_mediainfo)
            )

        script = self.comparison_pair.script
        if script and not script.is_file():
            raise FileNotFoundError(f"Comparison script no longer exists: {script}")

    def source_available(self) -> bool:
        """Whether every original media path is currently readable."""
        try:
            self.require_existing_media_paths(include_comparison=False)
        except (FileNotFoundError, RuntimeError):
            return False
        return True

    def input_is_directory(self) -> bool:
        """Return the saved input kind without requiring the path to exist."""
        if self.input_kind in {"file", "directory"}:
            return self.input_kind == "directory"
        return bool(self.input_path and self.input_path.is_dir())

    def apply_rename_mapping(
        self,
        rename_mapping: dict[Path, Path],
        updated_input_path: Path | None = None,
    ) -> None:
        """Re-point every path this payload holds at its renamed location.

        Called after the renames have been executed on disk. Every field keyed
        by (or holding) an input path has to move together, otherwise later
        pages look up a path that no longer exists, e.g. the screenshots page
        resolving `comparison_pair.media` against `file_list_mediainfo`. When
        a parent directory was renamed, paths under that directory are
        remapped even when their filenames did not change.

        Args:
            rename_mapping: Map of old path -> new path for renamed files.
            updated_input_path: New input path, when the rename moved it.
        """
        if not rename_mapping and not updated_input_path:
            return

        old_input_path = self.input_path

        def remap_path(path: Path) -> Path:
            """Apply an exact file mapping or an input-directory relocation."""
            mapped_path = rename_mapping.get(path)
            if mapped_path is not None:
                return mapped_path

            if (
                not old_input_path
                or not updated_input_path
                or not updated_input_path.is_dir()
            ):
                return path
            return _moved_tree(old_input_path, updated_input_path)(path)

        self._remap_paths(remap_path)

        if updated_input_path:
            self.input_path = updated_input_path

    def _remap_paths(self, remap: Callable[[Path], Path]) -> None:
        """Pass every path this payload holds, but `input_path`, through `remap`."""
        for i, old_path in enumerate(self.file_list):
            self.file_list[i] = remap(old_path)

        if self.file_list_mediainfo:
            self.file_list_mediainfo = {
                remap(old_path): mi_obj
                for old_path, mi_obj in self.file_list_mediainfo.items()
            }

        if self.series_episode_map:
            self.series_episode_map = {
                remap(old_path): ep_data
                for old_path, ep_data in self.series_episode_map.items()
            }

        # the comparison media is one of the renamed files; the source usually
        # sits outside the rename set but still moves when its folder is renamed
        if self.comparison_pair:
            self.comparison_pair = self.comparison_pair._replace(
                source=remap(self.comparison_pair.source),
                media=remap(self.comparison_pair.media),
                script=(
                    remap(self.comparison_pair.script)
                    if self.comparison_pair.script
                    else None
                ),
            )

        # a disc's root folder can be renamed; its playlists and clips move too
        for disc in self.discs:
            disc.relocate(remap)

    def reset(self, input_path: Path | None = None) -> None:
        """Reset all fields to initial state."""
        self.unmount_disc_images()
        self.analysis_cache.clear()
        self.input_path = input_path
        self.media_type = None
        self.working_dir = None
        self.file_list.clear()
        self.file_list_mediainfo.clear()
        self.input_kind = None
        self.content_size = None
        self.comparison_pair = None
        self.discs.clear()
        self.series_episode_map = None
        self.series_episode_format = EpisodeFormat.STANDARD
