"""Coverage for the working directory layout that keeps jobs safe from cleanup."""

from pathlib import Path

from src.backend.utils.working_dir import (
    JOBS_DIR_NAME,
    PROCESSING_DIR_NAME,
    cleanable_items,
    jobs_dir,
    processing_dir,
)


def test_jobs_and_processing_are_siblings(tmp_path: Path) -> None:
    assert jobs_dir(tmp_path) == tmp_path / JOBS_DIR_NAME
    assert processing_dir(tmp_path) == tmp_path / PROCESSING_DIR_NAME


def test_directories_are_only_created_when_asked(tmp_path: Path) -> None:
    jobs_dir(tmp_path)
    assert not (tmp_path / JOBS_DIR_NAME).exists()

    jobs_dir(tmp_path, ensure_exists=True)
    assert (tmp_path / JOBS_DIR_NAME).is_dir()


def test_cleanup_never_touches_saved_jobs(tmp_path: Path) -> None:
    """Clean up reclaims space; it must not be able to destroy saved work."""
    saved_job = jobs_dir(tmp_path, ensure_exists=True) / "job.json"
    saved_job.write_text("{}", encoding="utf-8")
    run_folder = processing_dir(tmp_path, ensure_exists=True) / "Some.Release"
    run_folder.mkdir(parents=True)

    removable = cleanable_items(tmp_path)

    assert processing_dir(tmp_path) in removable
    assert jobs_dir(tmp_path) not in removable


def test_cleanup_sweeps_run_folders_left_at_the_root(tmp_path: Path) -> None:
    """Older versions wrote run folders directly at the root; still clean them.

    Expressing cleanup as "everything except jobs" rather than "only the
    processing folder" is what removes the need for a migration step.
    """
    legacy_run = tmp_path / "Old.Release-20260101_120000"
    legacy_run.mkdir(parents=True)
    stray_file = tmp_path / "stray.log"
    stray_file.write_text("x", encoding="utf-8")
    jobs_dir(tmp_path, ensure_exists=True)

    removable = cleanable_items(tmp_path)

    assert legacy_run in removable
    assert stray_file in removable
    assert jobs_dir(tmp_path) not in removable


def test_cleanable_items_is_empty_for_a_missing_directory(tmp_path: Path) -> None:
    assert cleanable_items(tmp_path / "never-created") == []
