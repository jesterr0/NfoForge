from pathlib import Path
import sys


def _get_working_directories() -> tuple[Path, Path, bool]:
    """
    Used to determine the correct working directory automatically.
    This way we can utilize files/relative paths easily.

    Returns:
        (Path, Path, bool): Current working directory, runtime directory, frozen.
    """
    # we're in a pyinstaller bundle
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        path = Path(sys.executable).parent
        return path, path / "bundle" / "runtime", True

    # we're running from a *.py file
    else:
        path = Path.cwd()
        return path, path / "runtime", False


CURRENT_DIR, RUNTIME_DIR, IS_FROZEN = _get_working_directories()

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


# The user-configurable working directory is laid out so that disposable
# artifacts and deliberately saved work never share a parent. "Clean Up" in
# Settings -> General reclaims space by emptying everything *except* the jobs
# folder, so a saved job can't be destroyed by routine housekeeping.
JOBS_DIR_NAME = "jobs"
"""Saved jobs. Never removed by the working directory clean up."""

PROCESSING_DIR_NAME = "processing"
"""Per-run artifacts (screenshots, torrents, NFOs). Safe to delete."""

WORKSPACE_DIR_NAME = "workspace"
"""Parent of the two above, once the working directory lives inside `<user data>`.

Named here rather than in the layout migration that introduces it, because it is
the new parent of the two names above and splitting the three across modules
would invite the layout and the working directory drifting apart.
"""


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


def cleanable_items(working_dir: Path, data_root: Path) -> list[Path]:
    """Everything clean up may delete: the contents of the processing folder.

    Scoped to one directory rather than expressed as "everything except jobs".
    The exclusion form reached every sibling, which caught the run folders
    older versions wrote at the working directory root, but it also meant a
    working directory pointed at a folder holding anything else handed that
    content to the Clean Up button. Those legacy run folders are relocated
    into `processing/` by the one-time layout migration instead.

    The folder itself is not returned, only its entries, so it survives for
    the next run.

    `data_root` is the application's own per-user directory, and nothing is
    returned when emptying the processing folder would reach it. The narrowing
    above already makes that unreachable for any ordinary working directory;
    this states it as an invariant instead of leaving it to depend on which
    directory names the layout happens to use. Required rather than optional
    so a new caller that has not thought about it fails loudly.

    Same race `cleanable_size` guards one level down: the directory can be
    removed in the window between the `is_dir()` check and `iterdir()`
    actually running, and an unhandled `OSError` there would surface out of
    this function and out of `cleanable_size`, which iterates its result.
    """
    processing = processing_dir(working_dir)
    if normalise_path(data_root).is_relative_to(normalise_path(processing)):
        return []
    if not processing.is_dir():
        return []
    try:
        return list(processing.iterdir())
    except OSError:
        return []


def cleanable_size(working_dir: Path, data_root: Path) -> int:
    """Bytes clean up could reclaim.

    Two nested guards, because a scan can lose ground at two different levels.
    A single file can vanish between being listed and being stat()'d -- the
    inner guard skips just that file so its siblings still count toward the
    total. But the walk itself can also vanish out from under us: rglob()
    calls os.scandir() lazily as it descends and only swallows
    PermissionError, so if a whole subdirectory disappears mid-descent (a
    concurrent job's run folder, say) the exception surfaces from the `for`
    statement itself, past a guard sitting only in the loop body. The outer
    guard catches that case too, so one vanished top-level item doesn't cost
    us the count already gathered for the rest.
    """
    total = 0
    for item in cleanable_items(working_dir, data_root):
        try:
            if item.is_dir():
                for candidate in item.rglob("*"):
                    try:
                        if candidate.is_file():
                            total += candidate.stat().st_size
                    except OSError:
                        continue
            elif item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total
