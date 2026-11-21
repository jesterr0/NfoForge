from collections.abc import Iterable
from pathlib import Path
import re
import sys
import warnings

from nfoforge.enums.tracker_selection import TrackerSelection


def _get_working_directories() -> tuple[Path, bool]:
    """Where this process was launched from, and whether it is a frozen build.

    There used to be a third value here: a mutable tree inside the installation,
    which is where every piece of user state lived. Nothing reads it any more,
    because a path derived from the installation points at a directory a release
    replaces. User state comes from the per-user data directory now, via
    `AppPaths`, and files shipped with the release come from `asset_root`.

    The old name is still importable for plugins. See `__getattr__` below.
    """
    # we're in a pyinstaller bundle
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys.executable).parent, True

    # we're running from a *.py file
    return Path.cwd(), False


CURRENT_DIR, IS_FROZEN = _get_working_directories()
"""Where the process was launched from. Only startup's `.env` lookup wants this."""


ASSET_DIR_NAME = "assets"
"""Read-only files shipped with a release: fonts, images, SVGs, packaged defaults."""

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def asset_root() -> Path:
    """Where the files shipped with this release live.

    A function rather than a module constant so nothing binds a path at import
    time, and so tests can exercise both branches.

    Frozen builds ask PyInstaller via `sys._MEIPASS` instead of deriving a path
    from `sys.executable`. On Windows and Linux the two coincide, because
    `--contents-directory` renames PyInstaller's own folder to the same name the
    old exe-relative path used. They do not coincide on macOS, where the
    executable sits in `Contents/MacOS` and collected data does not, so an
    exe-relative path names a directory that is not there.

    From source the root is resolved against this file's location, not
    `Path.cwd()`, so launching from anywhere still finds the project's assets.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        return Path(meipass) / ASSET_DIR_NAME
    return _PROJECT_ROOT / ASSET_DIR_NAME


JOBS_DIR_NAME = "jobs"
"""Saved jobs. Never removed by the working directory clean up."""

PROCESSING_DIR_NAME = "processing"
"""Per-run artifacts (screenshots, torrents, NFOs). Safe to delete."""

FRAMEFORGE_INDEX_DIR_NAME = "frameforge_indexes"
"""Reusable FrameForge indexes for the working directory."""

WORKSPACE_DIR_NAME = "workspace"
"""Default working directory inside the application's data directory."""

_RUN_FOLDER_STAMP = re.compile(r"_\d{2}\.\d{2}\.\d{4}_\d{2}\.\d{2}\.\d{2}$")
_TRACKER_FILE_SUFFIXES = frozenset({".nfo", ".torrent"})
_IMAGE_FILE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})
_LEGACY_OUTPUT_DIRS = {
    **dict.fromkeys(
        (str(tracker).lower() for tracker in TrackerSelection), _TRACKER_FILE_SUFFIXES
    ),
    "images": _IMAGE_FILE_SUFFIXES,
    "dl_imgs": _IMAGE_FILE_SUFFIXES,
}


def normalise_path(path: Path) -> Path:
    """Return `path` in the form used to compare configured paths for identity.

    Configured paths arrive from TOML as whatever the user or an older release
    wrote, so one directory can be spelled several ways: a trailing separator,
    a parent hop, or relative to the process working directory. `resolve()`
    settles all of those.

    Case is deliberately not handled here, because `Path` already handles it:
    comparison and `is_relative_to` are case-insensitive on Windows, so two
    resolved paths differing only in case compare equal even though their
    strings do not. The value of naming this function is that it keeps those
    comparisons on `Path` -- comparing `str(a) == str(b)` is what reintroduces
    the bug -- and gives one place to extend if a spelling turns up that
    `resolve()` does not settle. One already exists: an 8.3 short name in a
    path that does not exist on disk cannot be expanded, because there is
    nothing to ask.
    """
    return Path(path).resolve()


def jobs_dir(working_dir: Path, ensure_exists: bool = False) -> Path:
    """Where saved jobs live for a given working directory."""
    path = working_dir / JOBS_DIR_NAME
    if ensure_exists:
        path.mkdir(parents=True, exist_ok=True)
    return path


def processing_dir(working_dir: Path, ensure_exists: bool = False) -> Path:
    """Where a run's generated artifacts live for a given working directory."""
    path = working_dir / PROCESSING_DIR_NAME
    if ensure_exists:
        path.mkdir(parents=True, exist_ok=True)
    return path


def has_run_folder_stamp(name: str) -> bool:
    """Match the timestamp appended by generate_unique_date_name."""
    return _RUN_FOLDER_STAMP.search(name) is not None


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _directory_items(directory: Path) -> list[Path]:
    try:
        return list(directory.iterdir())
    except OSError:
        return []


def _is_legacy_run(directory: Path) -> bool:
    """Require a timestamped run to contain only known generated artifacts."""

    def raise_scan_error(error: OSError) -> None:
        raise error

    found_artifacts = False
    try:
        if not directory.is_dir() or _is_link(directory):
            return False
        for root, dirs, files in directory.walk(on_error=raise_scan_error):
            if any(_is_link(root / name) for name in dirs):
                return False
            if root == directory:
                if any(name.lower() not in _LEGACY_OUTPUT_DIRS for name in dirs):
                    return False
                suffixes = _TRACKER_FILE_SUFFIXES
            else:
                output_dir = root.relative_to(directory).parts[0].lower()
                suffixes = _LEGACY_OUTPUT_DIRS[output_dir]
            for name in files:
                artifact = root / name
                if artifact.suffix.lower() not in suffixes or not artifact.is_file(
                    follow_symlinks=False
                ):
                    return False
                found_artifacts = True
    except OSError:
        return False
    return found_artifacts


def cleanable_items(working_dir: Path, data_root: Path) -> list[Path]:
    """Find generated output and cached indexes in this working directory."""
    data_root = normalise_path(data_root)
    removable = []
    for directory in (
        processing_dir(working_dir),
        working_dir / FRAMEFORGE_INDEX_DIR_NAME,
    ):
        if _is_link(directory) or data_root.is_relative_to(normalise_path(directory)):
            continue
        removable.extend(
            item for item in _directory_items(directory) if not _is_link(item)
        )

    # Layout migration leaves custom working directories in place. Require
    # evidence of generated output before deleting a folder at their root.
    for item in _directory_items(working_dir):
        if (
            has_run_folder_stamp(item.name)
            and _is_legacy_run(item)
            and not data_root.is_relative_to(normalise_path(item))
        ):
            removable.append(item)
    return removable


def cleanable_size(working_dir: Path, data_root: Path) -> int:
    """Bytes clean up could reclaim from the working directory."""
    return cleanup_items_size(cleanable_items(working_dir, data_root))


def cleanup_items_size(items: Iterable[Path]) -> int:
    """Measure the items in a cleanup preview.

    Two nested guards, because a scan can lose ground at two different levels.
    A single file can vanish between being listed and being stat()'d -- the
    inner guard skips just that file so its siblings still count toward the
    total. But the walk's iterator can also fail as it descends into a whole
    subdirectory (a concurrent job's run folder, say). That exception surfaces
    from the `for` statement itself, past a guard sitting only in the loop
    body. The outer guard catches that case too, so one vanished top-level item
    does not cost us the count already gathered for the rest.
    """
    total = 0
    for item in items:
        try:
            if item.is_dir(follow_symlinks=False):
                for root, dirs, files in item.walk():
                    # Windows junctions are directories to Path.walk. Cleanup
                    # unlinks them, so their targets do not count toward the size.
                    dirs[:] = [name for name in dirs if not (root / name).is_junction()]
                    for name in files:
                        candidate = root / name
                        try:
                            if candidate.is_file(follow_symlinks=False):
                                total += candidate.stat().st_size
                        except OSError:
                            continue
            elif item.is_file(follow_symlinks=False):
                total += item.stat().st_size
        except OSError:
            continue
    return total


def __getattr__(name: str) -> Path:
    """Keep `RUNTIME_DIR` importable for plugins built against it.

    It used to be the mutable tree inside the installation, and nothing in this
    application reads it any more -- a test asserts that. Plugins are
    user-installed and sometimes compiled, though, so this release cannot patch
    them, and an `ImportError` on a name they have always been able to import
    would stop them loading outright.

    So it still resolves, to the directory that now holds what it used to: the
    per-user state root. A plugin asking for `RUNTIME_DIR / "templates"` gets the
    templates, which is what it meant. Resolved on each access rather than bound
    once, because the state root depends on how the process was started.

    Warned rather than logged, because importing the logger here would be a
    cycle: the logger resolves its own path through the module that reads this
    one.
    """
    if name != "RUNTIME_DIR":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    warnings.warn(
        "RUNTIME_DIR is deprecated. User state moved out of the installation and "
        "into the per-user data directory; it resolves there now. Prefer the "
        "paths object a plugin is given, which names each location directly.",
        DeprecationWarning,
        stacklevel=2,
    )
    from nfoforge.config.paths import default_paths

    return default_paths().state_root
