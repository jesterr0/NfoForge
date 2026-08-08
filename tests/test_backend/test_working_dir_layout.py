"""Coverage for the working directory layout that keeps jobs safe from cleanup."""

import os
from pathlib import Path

import pytest

from src.backend.utils.working_dir import (
    JOBS_DIR_NAME,
    PROCESSING_DIR_NAME,
    cleanable_items,
    cleanable_size,
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


def test_cleanable_items_survives_the_directory_vanishing_before_iterdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The directory can be removed between the is_dir() check and iterdir().

    Same race cleanable_size guards one level down; unguarded here it would
    surface straight out of cleanable_items and out of cleanable_size too,
    since cleanable_size iterates this function's result.
    """
    working_dir = tmp_path / "nfoforge"
    working_dir.mkdir()

    real_iterdir = Path.iterdir

    def vanishing(self: Path) -> object:
        if self == working_dir:
            raise OSError("directory vanished mid-scan")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", vanishing)

    assert cleanable_items(working_dir) == []


def test_cleanable_size_adds_up_what_clean_up_would_remove(tmp_path: Path) -> None:
    processing = tmp_path / "processing" / "run"
    processing.mkdir(parents=True)
    (processing / "shot.png").write_bytes(b"x" * 100)
    jobs = tmp_path / "jobs" / "abc"
    jobs.mkdir(parents=True)
    (jobs / "job.json").write_bytes(b"y" * 500)
    (tmp_path / "stray.log").write_bytes(b"z" * 10)

    # jobs/ is never reclaimable, so it must not be counted
    assert cleanable_size(tmp_path) == 110


def test_cleanable_size_survives_a_file_disappearing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processing = tmp_path / "processing"
    processing.mkdir()
    (processing / "gone.png").write_bytes(b"x" * 100)

    real_stat = Path.stat

    def vanishing(self: Path, *args: object, **kwargs: object) -> object:
        if self.name == "gone.png":
            raise OSError("file vanished mid-scan")
        return real_stat(self, *args, **kwargs)  # pyright: ignore[reportCallIssue]

    monkeypatch.setattr(Path, "stat", vanishing)

    assert cleanable_size(tmp_path) == 0


def test_cleanable_size_survives_a_directory_disappearing_mid_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A whole subdirectory can vanish while rglob() is still descending into it.

    That surfaces as an exception from the `for` statement driving the walk,
    not from a stat() call inside the loop body, so it needs its own guard
    one level up from the per-file one.
    """
    keep = tmp_path / "processing" / "keep"
    keep.mkdir(parents=True)
    (keep / "shot.png").write_bytes(b"x" * 50)

    gone = tmp_path / "gone"
    gone.mkdir()
    (gone / "trace.log").write_bytes(b"x" * 30)

    real_scandir = os.scandir

    def vanishing(path: object = ".") -> object:
        if Path(path).name == "gone":
            raise FileNotFoundError("directory vanished mid-scan")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", vanishing)

    # "gone" disappears out from under the walk; only "keep" can still be measured
    assert cleanable_size(tmp_path) == 50


def test_cleanable_size_is_zero_for_a_missing_directory(tmp_path: Path) -> None:
    assert cleanable_size(tmp_path / "never-created") == 0


def test_cleanable_size_is_zero_for_an_empty_directory(tmp_path: Path) -> None:
    assert cleanable_size(tmp_path) == 0
