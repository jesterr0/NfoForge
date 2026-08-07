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


# The user-configurable working directory is laid out so that disposable
# artifacts and deliberately saved work never share a parent. "Clean Up" in
# Settings -> General reclaims space by emptying everything *except* the jobs
# folder, so a saved job can't be destroyed by routine housekeeping.
JOBS_DIR_NAME = "jobs"
"""Saved jobs. Never removed by the working directory clean up."""

PROCESSING_DIR_NAME = "processing"
"""Per-run artifacts (screenshots, torrents, NFOs). Safe to delete."""


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


def cleanable_items(working_dir: Path) -> list[Path]:
    """Everything clean up may delete: all of the working directory but jobs.

    Expressed as an exclusion rather than "only the processing folder" so that
    run folders written directly at the working directory root by older
    versions are swept up too, without needing a migration step.
    """
    if not working_dir.is_dir():
        return []
    return [item for item in working_dir.iterdir() if item.name != JOBS_DIR_NAME]


def cleanable_size(working_dir: Path) -> int:
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
    for item in cleanable_items(working_dir):
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
