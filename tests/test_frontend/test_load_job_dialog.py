"""Coverage for the saved-job picker's presentation and actions.

The save/resume round trip is covered in `test_job_save_resume.py`; what is
tested here is the dialog itself.
"""

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView
import pytest

from src.backend.jobs import store
from src.backend.jobs.models import JobSummary
from src.frontend.custom_widgets import load_job_dialog as load_job_dialog_module
from src.frontend.custom_widgets.load_job_dialog import LoadJobDialog


@pytest.fixture
def working_dir(tmp_path: Path) -> Path:
    return tmp_path / "nfoforge"


@pytest.fixture
def patched_working_dirs(working_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        load_job_dialog_module, "unique_working_dirs", lambda: [working_dir]
    )


def _save(
    working_dir: Path,
    name: str,
    *,
    profile: str = "default",
    prepared: bool = True,
    trackers: list[str] | None = None,
    title: str | None = None,
    created_at: str | None = None,
) -> Path:
    context: dict[str, Any] = {"shared_data": {}}
    if prepared:
        context["shared_data"]["tracker_release_data"] = {
            "AITHER": {"title": "t", "nfo": "body"}
        }
    job = store.build_job(
        name,
        JobSummary(title=title or name, year=2024, trackers=trackers or ["Aither"]),
        context,
        config_profile=profile,
    )
    if created_at:
        job.created_at = created_at
    return store.save_job(job, working_dir)


def test_columns_are_sized_for_what_they_hold(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "job")
    dialog = LoadJobDialog("default")
    header = dialog.job_tree.header()

    assert header.sectionResizeMode(0) is QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(2) is QHeaderView.ResizeMode.ResizeToContents
    assert header.sectionResizeMode(3) is QHeaderView.ResizeMode.Interactive
    assert dialog.job_tree.textElideMode() is Qt.TextElideMode.ElideRight


def test_the_full_tracker_list_is_available_as_a_tooltip(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "job", trackers=["Aither", "Huno", "LST", "DarkPeers"])
    dialog = LoadJobDialog("default")

    assert "DarkPeers" in dialog.job_tree.topLevelItem(0).toolTip(3)


def test_jobs_are_sortable_and_start_newest_first(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "older", created_at="2026-01-01T00:00:00+00:00")
    _save(working_dir, "newer", created_at="2026-06-01T00:00:00+00:00")
    dialog = LoadJobDialog("default")

    assert dialog.job_tree.isSortingEnabled()
    assert dialog.job_tree.topLevelItem(0).text(0) == "newer"


def test_the_dialog_can_be_resized_from_its_corner(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    dialog = LoadJobDialog("default")

    assert dialog.isSizeGripEnabled()


def test_the_info_label_does_not_repeat_the_window_title(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    dialog = LoadJobDialog("default")

    assert dialog.windowTitle() == "Saved Jobs"
    assert "<h3" not in dialog.info_lbl.text()
