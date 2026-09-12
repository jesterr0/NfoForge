from pathlib import Path
import sys
import warnings


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
    from src.config.paths import default_paths

    return default_paths().state_root
