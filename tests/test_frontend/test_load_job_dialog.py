"""Coverage for the saved-job picker's presentation and actions.

The save/resume round trip is covered in `test_job_save_resume.py`; what is
tested here is the dialog itself.
"""

from datetime import datetime
from pathlib import Path
import re
import time
from types import SimpleNamespace
from typing import Any

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox, QHeaderView, QMessageBox
import pytest
import qtawesome as qta

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
    archived: bool = False,
) -> Path:
    context: dict[str, Any] = {"shared_data": {}}
    if archived:
        context["media_input"] = {
            "mediainfo_assets": {"C:/gone.mkv": {"xml": "mediainfo/0.xml"}}
        }
    if prepared:
        # both halves, as a real prepared job has them: the trackers the run
        # will serve, and the frozen release for each of them
        context["shared_data"]["selected_trackers"] = ["AITHER"]
        context["shared_data"]["tracker_release_data"] = {
            "AITHER": {"title": "t", "nfo": "body"}
        }
    job = store.build_job(
        name,
        JobSummary(
            title=title or name,
            year=2024,
            trackers=["Aither"] if trackers is None else trackers,
        ),
        context,
        config_profile=profile,
        archived=archived,
    )
    if created_at:
        job.created_at = created_at
    directory = store.save_job(job, working_dir)
    if archived:
        (directory / store.JOB_BASE_TORRENT_NAME).write_bytes(b"torrent")
    return directory


# --------------------------------------------------------------------------
# resolving an upload nobody could confirm
# --------------------------------------------------------------------------
def _save_with_uncertain(working_dir: Path) -> Path:
    """An archive that ran two trackers and could not account for one.

    `AITHER` is the uncertain one, so it is held out of `selected_trackers`
    while keeping its title and NFO -- exactly what `_archive_completed_run`
    now writes.
    """
    context: dict[str, Any] = {
        "shared_data": {
            "selected_trackers": [],
            "tracker_release_data": {
                "AITHER": {"title": "the reviewed title", "nfo": "the reviewed nfo"},
            },
            "tracker_image_hosts": {
                "AITHER": {
                    "img_from": "IMAGES",
                    "img_to": "PIXHOST",
                    "img_to_type": "ImageHost",
                }
            },
        }
    }
    job = store.build_job(
        "uncertain archive",
        JobSummary(title="uncertain archive", year=2024, trackers=[]),
        context,
        archived=True,
        uploaded_trackers=["HUNO"],
        uncertain_trackers=["AITHER"],
    )
    return store.save_job(job, working_dir)


def _answer_resolve(monkeypatch: pytest.MonkeyPatch, answer: Any) -> None:
    monkeypatch.setattr(
        load_job_dialog_module.QMessageBox, "question", lambda *_a, **_k: answer
    )


def test_resolving_no_makes_the_tracker_runnable_again(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "No, safe to upload" has to mean the job can actually upload it.

    Moving the name between two lists was all this used to do, so the answer
    left the tracker out of `selected_trackers` and the job unchanged in every
    way that matters -- the resolution had no effect at all.
    """
    directory = _save_with_uncertain(working_dir)
    _answer_resolve(monkeypatch, QMessageBox.StandardButton.No)

    dialog = _open_dialog(qapp)
    try:
        _click_tree_item(dialog, dialog.job_tree.topLevelItem(0), qapp)
        dialog._resolve_uncertain()
        _wait_for_load(dialog, qapp)
    finally:
        dialog.deleteLater()

    reloaded = store.load_job(directory)
    shared = reloaded.context["shared_data"]
    assert reloaded.uncertain_trackers == []
    assert shared["selected_trackers"] == ["AITHER"]
    # the release the user reviewed, not a fresh render of it
    assert shared["tracker_release_data"]["AITHER"]["title"] == "the reviewed title"
    # `summary.trackers` stores display values, the context stores member names
    assert reloaded.summary.trackers == ["Aither"]


def test_resolving_yes_records_the_upload_without_reselecting(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It landed, so the one thing that must never happen is uploading again."""
    directory = _save_with_uncertain(working_dir)
    _answer_resolve(monkeypatch, QMessageBox.StandardButton.Yes)

    dialog = _open_dialog(qapp)
    try:
        _click_tree_item(dialog, dialog.job_tree.topLevelItem(0), qapp)
        dialog._resolve_uncertain()
        _wait_for_load(dialog, qapp)
    finally:
        dialog.deleteLater()

    reloaded = store.load_job(directory)
    assert reloaded.uncertain_trackers == []
    assert set(reloaded.uploaded_trackers) == {"AITHER", "HUNO"}
    assert reloaded.context["shared_data"]["selected_trackers"] == []


def test_cancelling_leaves_the_tracker_unresolved(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _save_with_uncertain(working_dir)
    _answer_resolve(monkeypatch, QMessageBox.StandardButton.Cancel)

    dialog = _open_dialog(qapp)
    try:
        _click_tree_item(dialog, dialog.job_tree.topLevelItem(0), qapp)
        dialog._resolve_uncertain()
        _wait_for_load(dialog, qapp)
    finally:
        dialog.deleteLater()

    reloaded = store.load_job(directory)
    assert reloaded.uncertain_trackers == ["AITHER"]
    assert reloaded.context["shared_data"]["selected_trackers"] == []


def test_resolving_no_refuses_a_tracker_whose_prepared_work_is_gone(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An older archive narrowed its uncertain tracker away entirely.

    There is no title or NFO left to upload, so it must not be re-selected --
    a "prepared" job that silently uploads a freshly rendered release is worse
    than one that says it cannot help.
    """
    context: dict[str, Any] = {
        "shared_data": {"selected_trackers": [], "tracker_release_data": {}}
    }
    job = store.build_job(
        "stripped archive",
        JobSummary(title="stripped archive", year=2024, trackers=[]),
        context,
        archived=True,
        uncertain_trackers=["AITHER"],
    )
    directory = store.save_job(job, working_dir)
    _answer_resolve(monkeypatch, QMessageBox.StandardButton.No)

    dialog = _open_dialog(qapp)
    try:
        _click_tree_item(dialog, dialog.job_tree.topLevelItem(0), qapp)
        dialog._resolve_uncertain()
        _wait_for_load(dialog, qapp)
    finally:
        dialog.deleteLater()

    reloaded = store.load_job(directory)
    assert reloaded.uncertain_trackers == []
    assert reloaded.context["shared_data"]["selected_trackers"] == []
    # and the summary must not claim it covers a tracker it cannot run
    assert reloaded.summary.trackers == []


def test_add_trackers_is_available_for_a_self_contained_archive(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "archive", archived=True, trackers=[])

    dialog = _open_dialog(qapp)
    try:
        assert dialog.add_trackers_btn.isEnabled()
        open_button = dialog.button_box.button(QDialogButtonBox.StandardButton.Open)
        assert open_button is not None
        assert not open_button.isEnabled()
    finally:
        dialog.deleteLater()


def test_double_clicking_a_spent_archive_asks_for_new_trackers(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """The disabled Load button was never the whole rule.

    An archive that has been everywhere it was run for has nothing for the
    process page to do, which is why Load is greyed out for it -- but a double
    click went straight to `_accept_selection` and loaded it anyway, landing on
    a process page whose only button failed with "Failed to generate tracker
    data". A double click now takes the action the row does offer.
    """
    _save(working_dir, "archive", archived=True, trackers=[])

    dialog = _open_dialog(qapp)
    try:
        item = dialog.job_tree.topLevelItem(0)
        assert item is not None
        dialog._on_double_click(item, 0)

        assert dialog.selected_listing is not None
        assert dialog.add_trackers_requested is True
    finally:
        dialog.deleteLater()


def test_a_spent_archive_cannot_be_loaded_by_pressing_open(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """`_accept_selection` enforces the rule rather than trusting the button."""
    _save(working_dir, "archive", archived=True, trackers=[])

    dialog = _open_dialog(qapp)
    try:
        item = dialog.job_tree.topLevelItem(0)
        assert item is not None
        dialog.job_tree.setCurrentItem(item)
        item.setSelected(True)
        dialog._accept_selection()

        assert dialog.selected_listing is None
    finally:
        dialog.deleteLater()


def test_an_archive_that_cannot_add_trackers_either_says_so_and_stays_put(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Neither route is open, so the click must not pretend one is.

    Without its base torrent the archive cannot be reopened for new trackers,
    which leaves a double click with nothing to do -- and a hint naming a
    disabled button would send the user at it anyway.
    """
    directory = _save(working_dir, "archive", archived=True, trackers=[])
    (directory / store.JOB_BASE_TORRENT_NAME).unlink()

    dialog = _open_dialog(qapp)
    try:
        item = dialog.job_tree.topLevelItem(0)
        assert item is not None
        _click_tree_item(dialog, item, qapp)
        assert not dialog.add_trackers_btn.isEnabled()
        assert "cannot be reopened" in dialog.status_lbl.text()

        dialog._on_double_click(item, 0)

        assert dialog.selected_listing is None
    finally:
        dialog.deleteLater()


def test_a_spent_archive_points_at_the_action_it_can_take(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "archive", archived=True, trackers=[])

    dialog = _open_dialog(qapp)
    try:
        item = dialog.job_tree.topLevelItem(0)
        assert item is not None
        _click_tree_item(dialog, item, qapp)

        assert "Add Trackers" in dialog.status_lbl.text()
    finally:
        dialog.deleteLater()


def test_double_clicking_an_ordinary_job_still_loads_it(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "plain")

    dialog = _open_dialog(qapp)
    try:
        item = dialog.job_tree.topLevelItem(0)
        assert item is not None
        dialog._on_double_click(item, 0)

        assert dialog.selected_listing is not None
        assert dialog.add_trackers_requested is False
        assert dialog.switch_profile_requested is False
    finally:
        dialog.deleteLater()


def _open_dialog(qapp: Any, active_profile: str | None = "default") -> LoadJobDialog:
    """Construct the dialog and wait for its background listing load to land.

    Listing now happens on a `_ListingLoader` thread, so a dialog fresh out of
    `__init__` has an empty tree until that thread's `loaded` signal is
    delivered. Every test below except the three under "loading is
    asynchronous" is about what happens once the list has arrived, not about
    the loading itself -- for those, waiting once here is the right fix, not
    a wait bolted into each test.

    Waiting here also keeps the loader thread from still being alive when the
    test function returns and the dialog is dropped: destroying a running
    `QThread` aborts the process outright, and this is the one place where
    that would be silent since nothing here calls `wait()` afterwards.
    """
    dialog = LoadJobDialog(active_profile)
    _wait_for_load(dialog, qapp)
    return dialog


def _wait_for_load(dialog: LoadJobDialog, qapp: Any) -> None:
    """Block until the dialog's current loader thread has finished and let
    its queued `loaded` signal reach `_on_listings_loaded` on this thread.

    Also used after `_delete_selected` / `_rename_selected`, which now kick
    off a fresh reload asynchronously -- calling it even when a particular
    action returned early (and so never reloaded) is harmless, since waiting
    on an already-finished thread returns immediately.
    """
    assert dialog._loader is not None
    dialog._loader.wait(5000)
    qapp.processEvents()


def _click_tree_item(dialog: LoadJobDialog, item: Any, qapp: Any) -> None:
    """Drive a real mouse click on a tree row.

    `itemSelectionChanged`/`currentRowChanged` fire only on an actual
    selection change, not on every click -- calling `setCurrentItem` or
    `setSelected` directly exercises exactly that already-working path and
    would not catch a regression in the click-tracking this simulates. The
    dialog must be shown first: `visualItemRect` spans every column (this
    tree has 7), which is wider than the offscreen viewport, so clicking its
    center can land outside the viewport and hit nothing -- column 0's own
    visual rect is what is actually visible and clickable.
    """
    dialog.show()
    rect = dialog.job_tree.visualRect(dialog.job_tree.indexFromItem(item, 0))
    QTest.mouseClick(
        dialog.job_tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center()
    )
    qapp.processEvents()


def _click_queue_row(dialog: LoadJobDialog, row: int, qapp: Any) -> None:
    """Drive a real mouse click on a queue row -- see `_click_tree_item`."""
    dialog.show()
    rect = dialog.queue_list.visualItemRect(dialog.queue_list.item(row))
    QTest.mouseClick(
        dialog.queue_list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center()
    )
    qapp.processEvents()


def _answer_rename_prompt(
    monkeypatch: pytest.MonkeyPatch, typed: str, *, accepted: bool = True
) -> None:
    """Answer the rename prompt with `typed` without ever showing it.

    `_change_job_name` builds a `QInputDialog` and `exec()`s it, rather than
    going through `QInputDialog.getText`, so it can be sized before it opens.
    A modal `exec()` with nobody to dismiss it hangs the run outright -- not
    a failure with a message, just a test that never returns -- so every
    rename test has to stub the prompt, and stubbing the class method the
    prompt no longer uses would silently do nothing.

    Patched at `exec`/`textValue` rather than at `_change_job_name` itself so
    the helper's own behaviour -- notably the strip it applies to what was
    typed, which is what keeps a blank field from blanking a job's name --
    stays inside what these tests cover.

    `exec` is patched on `QDialog` rather than on `QInputDialog` because that
    is the class it is actually defined on -- `QInputDialog` merely inherits
    it. Patching the subclass would leave the attribute behind on teardown
    (monkeypatch restores the value it read, which for an inherited name means
    writing it onto the subclass), and it is `QDialog.exec` that the suite-wide
    modal guard in `tests/conftest.py` replaces, so overriding it here is what
    lets this one prompt through. `textValue` is `QInputDialog`'s own, so it
    is patched there.
    """
    code = (
        load_job_dialog_module.QDialog.DialogCode.Accepted
        if accepted
        else load_job_dialog_module.QDialog.DialogCode.Rejected
    )
    monkeypatch.setattr(load_job_dialog_module.QDialog, "exec", lambda _self: code)
    monkeypatch.setattr(
        load_job_dialog_module.QInputDialog, "textValue", lambda _self: typed
    )


def test_columns_are_sized_for_what_they_hold(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Every column sizes to its own contents, and the panel scrolls.

    The three parts are one decision, not three: with all seven columns on
    ResizeToContents the row is as wide as it needs to be rather than as wide
    as the panel, so the tree needs a horizontal scrollbar to reach the right
    of it, and the last section must not stretch or it would absorb the slack
    and put the columns back out of step with their contents.
    """
    _save(working_dir, "job")
    dialog = _open_dialog(qapp)
    header = dialog.job_tree.header()

    for column in range(dialog.job_tree.columnCount()):
        assert header.sectionResizeMode(column) is (
            QHeaderView.ResizeMode.ResizeToContents
        ), f"column {column}"
    assert header.stretchLastSection() is False
    assert (
        dialog.job_tree.horizontalScrollBarPolicy()
        is Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    assert dialog.job_tree.textElideMode() is Qt.TextElideMode.ElideRight


def test_the_full_tracker_list_is_available_as_a_tooltip(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "job", trackers=["Aither", "Huno", "LST", "DarkPeers"])
    dialog = _open_dialog(qapp)

    assert "DarkPeers" in dialog.job_tree.topLevelItem(0).toolTip(3)


def test_the_list_opens_sorted_newest_first(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Assert the sort is configured, not that the rows happen to be in order.

    `list_jobs` already returns newest-first, so checking row 0 proves nothing
    -- it passes with sorting switched off entirely. The sort indicator is what
    only `sortByColumn` can set.

    Checked again after a reload (triggered the same way delete and rename
    trigger one) because the flag and indicator are set by the populate path
    on every call, not only by dialog construction.
    """
    _save(working_dir, "older", created_at="2026-01-01T00:00:00+00:00")
    _save(working_dir, "newer", created_at="2026-06-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)

    header = dialog.job_tree.header()
    assert dialog.job_tree.isSortingEnabled()
    assert header.sortIndicatorSection() == 6
    assert header.sortIndicatorOrder() is Qt.SortOrder.DescendingOrder
    assert dialog.job_tree.topLevelItem(0).text(0) == "newer"

    dialog._load_listings()
    _wait_for_load(dialog, qapp)

    assert dialog.job_tree.isSortingEnabled()
    assert header.sortIndicatorSection() == 6
    assert header.sortIndicatorOrder() is Qt.SortOrder.DescendingOrder
    assert dialog.job_tree.topLevelItem(0).text(0) == "newer"


def test_the_list_can_be_re_sorted_by_another_column(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Proves the widget sorts, rather than that its input arrived sorted.

    Names are chosen so alphabetical order is the reverse of newest-first: only
    a live sort can put "alpha" above "zulu" here.
    """
    _save(working_dir, "zulu", created_at="2026-06-01T00:00:00+00:00")
    _save(working_dir, "alpha", created_at="2026-01-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)

    dialog.job_tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    assert [
        dialog.job_tree.topLevelItem(index).text(0)
        for index in range(dialog.job_tree.topLevelItemCount())
    ] == ["alpha", "zulu"]


def test_the_dialog_can_be_resized_from_its_corner(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    dialog = _open_dialog(qapp)

    assert dialog.isSizeGripEnabled()


def test_the_info_label_does_not_repeat_the_window_title(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    dialog = _open_dialog(qapp)

    assert dialog.windowTitle() == "Saved Jobs"
    assert "<h3" not in dialog.info_lbl.text()


def test_filtering_matches_name_title_and_tracker(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "alpha", title="Alpha Movie", trackers=["Aither"])
    _save(working_dir, "beta", title="Beta Movie", trackers=["Huno"])
    dialog = _open_dialog(qapp)

    dialog.filter_edit.setText("huno")

    visible = [
        dialog.job_tree.topLevelItem(i).text(0)
        for i in range(dialog.job_tree.topLevelItemCount())
        if not dialog.job_tree.topLevelItem(i).isHidden()
    ]
    assert visible == ["beta"]


def test_filtering_matches_input_name(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """The placeholder promises filtering by file works, so `_apply_filter`'s
    haystack has to actually include `input_name` -- a filter that only
    searched `name`, `title` and `trackers` would leave that promise broken
    for a user filtering by the source filename.
    """
    job = store.build_job(
        "job",
        JobSummary(
            title="Some Title",
            trackers=["Aither"],
            input_name="Distinctive.Source.File.mkv",
        ),
        {"shared_data": {}},
        config_profile="default",
    )
    store.save_job(job, working_dir)
    dialog = _open_dialog(qapp)

    assert "file" in dialog.filter_edit.placeholderText().casefold()

    dialog.filter_edit.setText("distinctive.source.file")

    assert not dialog.job_tree.topLevelItem(0).isHidden()


def test_only_this_config_hides_other_profiles_by_default(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "mine", profile="default")
    _save(working_dir, "theirs", profile="anime")
    dialog = _open_dialog(qapp)

    assert dialog.only_this_config.isChecked()
    hidden = {
        dialog.job_tree.topLevelItem(i).text(0)
        for i in range(dialog.job_tree.topLevelItemCount())
        if dialog.job_tree.topLevelItem(i).isHidden()
    }
    assert hidden == {"theirs"}


def test_unchecking_only_this_config_reveals_other_profiles(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "theirs", profile="anime")
    dialog = _open_dialog(qapp)

    dialog.only_this_config.setChecked(False)

    assert not dialog.job_tree.topLevelItem(0).isHidden()


def test_hiding_a_row_also_deselects_it(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """A hidden row left selected would silently take part in Load or Delete."""
    _save(working_dir, "alpha")
    dialog = _open_dialog(qapp)
    dialog.job_tree.topLevelItem(0).setSelected(True)

    dialog.filter_edit.setText("nothing matches this")

    assert dialog._selected_listings() == []


def test_a_row_hidden_while_selected_does_not_come_back_selected(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Clearing a filter must not resurrect a selection the user cannot see.

    This is what the explicit `setSelected(False)` is actually for, and it is
    the only thing that exercises it. `selectedItems()` already skips hidden
    rows, so while the filter is on, hiding alone is enough -- but
    `isSelected()` survives hiding, so without the deselect the row reappears
    already selected once the filter clears, a selection the user never made
    and never saw happen.
    """
    _save(working_dir, "alpha")
    _save(working_dir, "beta")
    dialog = _open_dialog(qapp)
    for index in range(dialog.job_tree.topLevelItemCount()):
        dialog.job_tree.topLevelItem(index).setSelected(True)

    dialog.filter_edit.setText("alpha")
    dialog.filter_edit.setText("")

    rows = [
        dialog.job_tree.topLevelItem(index)
        for index in range(dialog.job_tree.topLevelItemCount())
    ]
    assert all(not row.isHidden() for row in rows)
    # "beta" was hidden and so deselected; "alpha" never was, so it stays
    assert sorted(row.text(0) for row in rows if row.isSelected()) == ["alpha"]


def test_a_mixed_selection_explains_why_the_queue_is_unavailable(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """`queue_btn` now reflects the queue list, not the selection -- it would
    be disabled here regardless, since nothing has been added yet. What a
    mixed selection actually still gates is whether it can be *added*.
    """
    _save(working_dir, "ready", prepared=True)
    _save(working_dir, "not-ready", prepared=False)
    dialog = _open_dialog(qapp)
    dialog.job_tree.selectAll()

    assert not dialog.add_to_queue_btn.isEnabled()
    assert "not prepared" in dialog.status_lbl.text()


def test_selection_hint_counts_a_doubly_blocked_job_once(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """`unprepared` and `other_config` are counted independently, so a job
    matching both reasons used to be counted in each -- one problem job read
    as two. The headline now counts blocked jobs once, with the per-reason
    counts kept only as a breakdown, so no number in the message can exceed
    the number of jobs actually selected.

    A selection of exactly one such job cannot exercise this: `_selection_hint`
    special-cases a size-one selection before reaching the reason-counting
    code below, reporting the profile mismatch instead of the reasons list.
    Reaching the code under test needs at least one other job alongside it.
    """
    _save(working_dir, "problem", prepared=False, profile="anime")
    _save(working_dir, "fine", prepared=True, profile="default")
    dialog = _open_dialog(qapp)
    dialog.only_this_config.setChecked(False)
    dialog.job_tree.selectAll()
    selected = dialog._selected_listings()
    assert len(selected) == 2

    hint = dialog._selection_hint()

    assert hint == (
        "2 selected; 1 cannot be added to the queue (1 not prepared, "
        "1 on another config). A queue has nobody to answer a prompt."
    )
    for number in re.findall(r"\d+", hint):
        assert int(number) <= len(selected)


def test_a_cross_profile_selection_says_which_config_it_needs(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "theirs", profile="anime")
    dialog = _open_dialog(qapp)
    dialog.only_this_config.setChecked(False)
    dialog.job_tree.topLevelItem(0).setSelected(True)
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))

    assert "anime" in dialog.status_lbl.text()


def test_double_clicking_a_cross_profile_row_offers_the_switch(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Silently doing nothing is the current behaviour and the worst option."""
    _save(working_dir, "theirs", profile="anime")
    dialog = _open_dialog(qapp)
    dialog.only_this_config.setChecked(False)
    item = dialog.job_tree.topLevelItem(0)
    dialog.job_tree.setCurrentItem(item)

    dialog._on_double_click(item, 0)

    assert dialog.switch_profile_requested is True
    assert dialog.selected_listing is not None


def test_double_clicking_a_same_profile_row_just_opens_it(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """The ordinary case: a double click on a row already on the active
    profile must accept the dialog and select that job outright, without
    ever offering the profile switch.

    This matters more than an ordinary coverage gap: the cross-profile
    branch calls `load_profile()`, which changes persistent global config.
    Pinning which branch runs is what stops the ordinary case from silently
    acquiring that side effect.
    """
    job_dir = _save(working_dir, "mine")
    dialog = _open_dialog(qapp)
    item = dialog.job_tree.topLevelItem(0)
    dialog.job_tree.setCurrentItem(item)

    dialog._on_double_click(item, 0)

    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.switch_profile_requested is False
    assert dialog.selected_listing is not None
    assert dialog.selected_listing.path == job_dir


def test_state_column_carries_an_icon(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "job", prepared=True)
    dialog = _open_dialog(qapp)

    assert not dialog.job_tree.topLevelItem(0).icon(5).isNull()


def test_the_state_icon_is_chosen_by_the_job_s_own_state(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """A non-null icon on one row proves only that *an* icon was set, and the
    two icons merely differing from each other proves only that they are not
    identical -- both a "same icon for every row" bug and a "states swapped"
    bug would be missed by that alone: a swap still leaves two distinct,
    non-null icons, just attached to the wrong rows.

    `qtawesome` caches by (icon name, color), so calling `qta.icon()` here
    with production's exact name and color reproduces the same `QIcon`
    `cacheKey()` -- verified empirically, not assumed -- which is what lets
    each row's icon be checked against the specific icon it should hold,
    not just against its sibling.

    Rows are collected into a dict keyed by name rather than read by
    position: newly-saved jobs can tie on `created_at` to the second, and the
    listing's tie-break sorts by job id, a random `shortuuid` -- so which row
    lands at index 0 is not deterministic between runs.
    """
    _save(working_dir, "ready", prepared=True)
    _save(working_dir, "draft", prepared=False)
    dialog = _open_dialog(qapp)

    rows = {}
    for index in range(dialog.job_tree.topLevelItemCount()):
        item = dialog.job_tree.topLevelItem(index)
        rows[item.text(0)] = item

    icon_color = dialog.palette().color(QPalette.ColorRole.WindowText).name()
    prepared_icon = qta.icon("mdi6.package-variant-closed", color=icon_color)
    needs_input_icon = qta.icon("mdi6.pencil-outline", color=icon_color)

    assert rows["ready"].icon(5).cacheKey() == prepared_icon.cacheKey()
    assert rows["draft"].icon(5).cacheKey() == needs_input_icon.cacheKey()


def test_delete_removes_every_selected_job(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save(working_dir, "one")
    _save(working_dir, "two")
    dialog = _open_dialog(qapp)
    dialog.job_tree.selectAll()
    monkeypatch.setattr(
        load_job_dialog_module.QMessageBox,
        "question",
        lambda *_a, **_k: load_job_dialog_module.QMessageBox.StandardButton.Yes,
    )

    dialog._delete_selected()
    _wait_for_load(dialog, qapp)

    assert dialog.job_tree.topLevelItemCount() == 0
    assert list((working_dir / "jobs").iterdir()) == []


def test_delete_only_removes_the_selected_job(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dangerous failure mode here is deleting more than was selected.

    Asserting the selected job's directory is gone would also pass a delete
    that wipes every saved job on disk -- what actually catches an
    over-broad delete is checking that the job which was *not* selected is
    still there.
    """
    kept_dir = _save(working_dir, "keep")
    _save(working_dir, "remove")
    dialog = _open_dialog(qapp)
    # `_on_listings_loaded` already leaves row 0 selected via `setCurrentItem`.
    # Without clearing it first, `setSelected(True)` below only *adds* "remove"
    # to that selection -- and this test happens to pass regardless, because
    # both jobs tie on the "Saved" column and "remove" is the one the tie
    # lands on row 0. That is not something this test states or controls, so
    # renaming either fixture job would make the tie-break, not the targeting
    # logic, decide whether it passes.
    dialog.job_tree.clearSelection()
    item = dialog.job_tree.findItems("remove", Qt.MatchFlag.MatchExactly, 0)[0]
    item.setSelected(True)
    monkeypatch.setattr(
        load_job_dialog_module.QMessageBox,
        "question",
        lambda *_a, **_k: load_job_dialog_module.QMessageBox.StandardButton.Yes,
    )

    dialog._delete_selected()
    _wait_for_load(dialog, qapp)

    assert kept_dir.exists()
    assert [
        dialog.job_tree.topLevelItem(index).text(0)
        for index in range(dialog.job_tree.topLevelItemCount())
    ] == ["keep"]


def test_the_delete_confirmation_names_what_it_will_remove(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save(working_dir, "alpha")
    _save(working_dir, "beta")
    dialog = _open_dialog(qapp)
    dialog.job_tree.selectAll()
    asked: list[str] = []

    def capture(_parent: Any, _title: str, text: str, *_a: Any, **_k: Any) -> Any:
        asked.append(text)
        return load_job_dialog_module.QMessageBox.StandardButton.No

    monkeypatch.setattr(load_job_dialog_module.QMessageBox, "question", capture)

    dialog._delete_selected()
    _wait_for_load(dialog, qapp)

    assert "alpha" in asked[0] and "beta" in asked[0]


def test_the_delete_key_is_wired_to_delete(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    dialog = _open_dialog(qapp)

    assert dialog.delete_btn.shortcut() == Qt.Key.Key_Delete


def test_the_f2_key_is_wired_to_rename(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    dialog = _open_dialog(qapp)

    assert dialog.rename_btn.shortcut() == Qt.Key.Key_F2


def test_a_job_with_missing_media_is_marked_in_the_list(
    qapp: Any, working_dir: Path, patched_working_dirs: None, tmp_path: Path
) -> None:
    job = store.build_job(
        "broken",
        JobSummary(title="Broken", input_path=str(tmp_path / "nope.mkv")),
        {"shared_data": {}},
        config_profile="default",
    )
    store.save_job(job, working_dir)
    dialog = _open_dialog(qapp)

    item = dialog.job_tree.topLevelItem(0)
    assert not item.icon(0).isNull()
    assert "no longer" in item.toolTip(0)


def test_the_details_pane_describes_the_selected_job(
    qapp: Any, working_dir: Path, patched_working_dirs: None, tmp_path: Path
) -> None:
    media = tmp_path / "Example.2024.mkv"
    media.write_bytes(b"x" * 20)
    job = store.build_job(
        "Example",
        JobSummary(
            title="Example",
            year=2024,
            media_type="Movie",
            input_path=str(media),
            file_count=1,
            trackers=["Aither"],
        ),
        {
            "shared_data": {
                "loaded_images": ["a.png", "b.png"],
                "tracker_image_hosts": {
                    "AITHER": {
                        "img_from": "IMAGES",
                        "img_to": "CHEVERETO_V3",
                        "img_to_type": "ImageHost",
                    }
                },
            }
        },
        config_profile="default",
    )
    job.created_at = "2020-01-01T00:00:00+00:00"
    directory = store.save_job(job, working_dir)

    # A second job the pane must not bleed into. With only one job saved,
    # assertions on substrings alone would still pass if the pane rendered
    # nothing at all, or the wrong row's data -- there would be nothing else
    # to distinguish it from. Pinning it newer than "Example" also makes it
    # the tree's default (post-sort) row, so a details pane that quietly
    # ignores the selection and shows row 0 shows this job, not "Example".
    decoy = store.build_job(
        "Decoy",
        JobSummary(title="Decoy", year=2020, trackers=["Huno"]),
        {
            "shared_data": {
                "loaded_images": ["c.png"],
                "tracker_image_hosts": {
                    "HUNO": {
                        "img_from": "IMAGES",
                        "img_to": "PTPIMG",
                        "img_to_type": "ImageHost",
                    }
                },
            }
        },
        config_profile="default",
    )
    decoy.created_at = "2020-06-01T00:00:00+00:00"
    store.save_job(decoy, working_dir)

    dialog = _open_dialog(qapp)
    item = dialog.job_tree.findItems("Example", Qt.MatchFlag.MatchExactly, 0)[0]
    dialog.job_tree.setCurrentItem(item)

    text = dialog.details_lbl.text()
    assert "Example" in text
    assert "Aither" in text
    # Both halves of the tracker row are stored as enum member names and both
    # must be resolved for display -- checking only the tracker leaves the
    # destination free to render as the raw "CHEVERETO_V3" beside a
    # humanised "Aither".
    assert "Chevereto v3" in text
    assert "CHEVERETO_V3" not in text
    assert "2 screenshot" in text
    assert str(directory) in text
    # none of the decoy job's own data belongs here
    assert "Decoy" not in text
    assert "Huno" not in text
    assert "PTPIMG" not in text
    assert "1 screenshot" not in text


def test_the_details_pane_is_cleared_when_nothing_is_selected(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    dialog = _open_dialog(qapp)

    assert dialog.details_lbl.text() == ""
    assert not dialog.open_folder_btn.isEnabled()


def test_the_details_pane_clears_once_a_selection_is_lost(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """The empty-dialog case above can pass on the widgets' own construction
    defaults alone, without `_refresh_details` ever running -- it does not by
    itself prove the pane reacts to a selection going away. Populating the
    pane first, then hiding the selected row via the filter, is what actually
    exercises that path.
    """
    _save(working_dir, "alpha")
    dialog = _open_dialog(qapp)
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))
    assert dialog.details_lbl.text() != ""
    assert dialog.open_folder_btn.isEnabled()

    dialog.filter_edit.setText("nothing matches this")

    assert dialog.details_lbl.text() == ""
    assert not dialog.open_folder_btn.isEnabled()


def test_refreshing_details_for_the_same_listing_does_not_re_read_the_document(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_describe` parses the job document and walks its folder -- the same
    read this branch already moved off-thread for `list_jobs`, so repeating it
    on every keystroke or on an unrelated selection change would undo that.

    `queue_list.currentRowChanged` feeds the same `_update_button_state` ->
    `_refresh_details` chain the tree's own selection does, so moving the
    queue selection alone -- with the tree's current item unchanged -- has to
    be a no-op here too, not just a direct repeated call.
    """
    _save(working_dir, "job")
    dialog = _open_dialog(qapp)
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))
    dialog.job_tree.topLevelItem(0).setSelected(True)
    dialog._add_to_queue()
    assert dialog.details_lbl.text() != ""

    calls: list[Path] = []
    real_load_job = load_job_dialog_module.load_job

    def counting_load_job(path: Path) -> Any:
        calls.append(path)
        return real_load_job(path)

    monkeypatch.setattr(load_job_dialog_module, "load_job", counting_load_job)

    dialog._refresh_details()
    dialog.queue_list.setCurrentRow(0)

    assert calls == []


def test_selecting_a_queue_row_describes_that_job(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Clicking a queue row must describe the queued job, not whatever the
    tree's own selection still points at -- the two panes used to share one
    detail view, driven only by the tree's current item, so selecting a
    queued job told the user nothing about it.

    The tree selection is left on a *different* job throughout, so this
    cannot pass by the pane coincidentally still showing the right thing.
    """
    _save(working_dir, "tree-job", created_at="2026-06-01T00:00:00+00:00")
    _save(working_dir, "queue-job", created_at="2026-01-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)
    tree_item = dialog.job_tree.findItems("tree-job", Qt.MatchFlag.MatchExactly, 0)[0]
    queue_source_item = dialog.job_tree.findItems(
        "queue-job", Qt.MatchFlag.MatchExactly, 0
    )[0]

    # Queue "queue-job" without disturbing the eventual tree selection.
    dialog.job_tree.clearSelection()
    queue_source_item.setSelected(True)
    dialog._add_to_queue()
    queue_source_item.setSelected(False)

    # Leave the tree selected on "tree-job" -- the pane must not describe this.
    dialog.job_tree.setCurrentItem(tree_item)
    tree_item.setSelected(True)
    assert "tree-job" in dialog.details_lbl.text()
    assert "queue-job" not in dialog.details_lbl.text()

    dialog.queue_list.setCurrentRow(0)

    assert "queue-job" in dialog.details_lbl.text()
    assert "tree-job" not in dialog.details_lbl.text()


def test_changing_the_tree_selection_after_a_queue_row_describes_the_tree_job_again(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Once a queue row has taken over the pane, the tree's own selection has
    to be able to take it back -- the pane describes whichever pane the user
    last interacted with, not permanently whichever was clicked first.
    """
    _save(working_dir, "tree-job", created_at="2026-06-01T00:00:00+00:00")
    _save(working_dir, "queue-job", created_at="2026-01-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)
    tree_item = dialog.job_tree.findItems("tree-job", Qt.MatchFlag.MatchExactly, 0)[0]
    queue_source_item = dialog.job_tree.findItems(
        "queue-job", Qt.MatchFlag.MatchExactly, 0
    )[0]

    dialog.job_tree.clearSelection()
    queue_source_item.setSelected(True)
    dialog._add_to_queue()
    queue_source_item.setSelected(False)
    dialog.job_tree.setCurrentItem(tree_item)
    tree_item.setSelected(True)

    dialog.queue_list.setCurrentRow(0)
    assert "queue-job" in dialog.details_lbl.text()

    # Re-select the tree's row -- a real change to the tree's selection, not
    # a repeat of a call that would already be a no-op.
    tree_item.setSelected(False)
    tree_item.setSelected(True)

    assert "tree-job" in dialog.details_lbl.text()
    assert "queue-job" not in dialog.details_lbl.text()


def test_open_folder_acts_on_the_queue_row_while_it_is_the_source(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Open Folder has to follow the same source as the details pane it sits
    under -- otherwise the pane can describe a queued job while the button
    opens a different one, lying about what it acts on.
    """
    tree_dir = _save(working_dir, "tree-job", created_at="2026-06-01T00:00:00+00:00")
    queue_dir = _save(working_dir, "queue-job", created_at="2026-01-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)
    tree_item = dialog.job_tree.findItems("tree-job", Qt.MatchFlag.MatchExactly, 0)[0]
    queue_source_item = dialog.job_tree.findItems(
        "queue-job", Qt.MatchFlag.MatchExactly, 0
    )[0]

    dialog.job_tree.clearSelection()
    queue_source_item.setSelected(True)
    dialog._add_to_queue()
    queue_source_item.setSelected(False)
    dialog.job_tree.setCurrentItem(tree_item)
    tree_item.setSelected(True)

    dialog.queue_list.setCurrentRow(0)

    opened: list[Path] = []
    monkeypatch.setattr(
        load_job_dialog_module, "open_explorer", lambda path: opened.append(path)
    )

    dialog.open_folder_btn.click()

    assert opened == [queue_dir]
    assert opened != [tree_dir]


# --------------------------------------------------------------------------
# T18 fix round 1: click tracking and programmatic-change suppression
# --------------------------------------------------------------------------
def test_re_clicking_a_queue_row_restores_its_pane(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """`currentRowChanged`/`itemSelectionChanged` fire only on an actual
    change, not on every click -- so re-clicking a queue row that is already
    `queue_list.currentRow()` emits nothing under selection-only wiring, and
    the pane silently keeps showing whatever was selected last. With a
    single-item queue there is no way back to that job short of removing and
    re-adding it. `itemClicked` fires on every press, including a re-click,
    which is what this test needs `_click_queue_row`'s real click -- not
    `setCurrentRow` -- to actually exercise.
    """
    _save(working_dir, "tree-job", created_at="2026-01-01T00:00:00+00:00")
    _save(working_dir, "queue-job", created_at="2026-06-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)
    tree_item = dialog.job_tree.findItems("tree-job", Qt.MatchFlag.MatchExactly, 0)[0]
    queue_source_item = dialog.job_tree.findItems(
        "queue-job", Qt.MatchFlag.MatchExactly, 0
    )[0]
    assert dialog.job_tree.currentItem() is queue_source_item

    dialog._add_to_queue()
    dialog.job_tree.clearSelection()

    _click_queue_row(dialog, 0, qapp)
    assert dialog._details_source == "queue"
    assert "queue-job" in dialog.details_lbl.text()

    _click_tree_item(dialog, tree_item, qapp)
    assert dialog._details_source == "tree"
    assert "tree-job" in dialog.details_lbl.text()

    # the same queue row again -- still queue_list.currentRow(), so
    # currentRowChanged emits nothing; only itemClicked can catch this
    _click_queue_row(dialog, 0, qapp)
    assert dialog._details_source == "queue"
    assert "queue-job" in dialog.details_lbl.text()


def test_a_filter_keystroke_does_not_steal_a_queue_sourced_pane(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """`_apply_filter` deselects every row it hides, which fires
    `itemSelectionChanged` for a row that was selected. If that flips the
    source to "tree" unconditionally, typing in the filter box silently
    discards a queue-sourced pane the user was looking at -- even though the
    user never touched the tree or the queue.
    """
    _save(working_dir, "row-a", created_at="2026-01-01T00:00:00+00:00")
    _save(working_dir, "row-b", created_at="2026-06-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)
    row_a = dialog.job_tree.findItems("row-a", Qt.MatchFlag.MatchExactly, 0)[0]
    row_b = dialog.job_tree.findItems("row-b", Qt.MatchFlag.MatchExactly, 0)[0]

    _click_tree_item(dialog, row_b, qapp)
    dialog._add_to_queue()
    _click_tree_item(dialog, row_a, qapp)
    assert dialog._details_source == "tree"
    assert row_a.isSelected()

    _click_queue_row(dialog, 0, qapp)
    assert dialog._details_source == "queue"
    assert "row-b" in dialog.details_lbl.text()

    # row A is still selected in the tree; hiding it must not touch the
    # source, which the user set by clicking the queue row above
    QTest.keyClicks(dialog.filter_edit, "row-b")
    qapp.processEvents()

    assert row_a.isHidden()
    assert dialog._details_source == "queue"
    assert "row-b" in dialog.details_lbl.text()
    assert dialog.open_folder_btn.isEnabled()


def test_the_pane_falls_back_to_the_tree_job_once_its_queue_row_is_gone(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Removing the queue row the pane is describing empties
    `queue_list.currentItem()` out from under a queue-sourced pane -- a
    different widget's action, not the user switching away. A pane that goes
    blank because of it reads as a glitch; falling back to the tree's own
    listing always leaves something sensible on screen.

    Not part of the brief's required A/B/E tests, but added because a
    mutation check against the pre-existing suite (reverting the fallback to
    a bare `return None`) showed nothing in the suite caught it -- the
    brief's claim that C is "covered by the existing suite" did not hold
    empirically, unlike D's tree-branch behaviour, which a mutation check
    confirmed really is already covered.
    """
    _save(working_dir, "tree-job", created_at="2026-01-01T00:00:00+00:00")
    _save(working_dir, "queue-job", created_at="2026-06-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)
    tree_item = dialog.job_tree.findItems("tree-job", Qt.MatchFlag.MatchExactly, 0)[0]
    queue_source_item = dialog.job_tree.findItems(
        "queue-job", Qt.MatchFlag.MatchExactly, 0
    )[0]

    dialog.job_tree.clearSelection()
    queue_source_item.setSelected(True)
    dialog._add_to_queue()
    queue_source_item.setSelected(False)
    dialog.job_tree.setCurrentItem(tree_item)
    tree_item.setSelected(True)

    dialog.queue_list.setCurrentRow(0)
    assert dialog._details_source == "queue"
    assert "queue-job" in dialog.details_lbl.text()

    dialog._remove_queued()

    assert dialog.details_lbl.text() != ""
    assert "tree-job" in dialog.details_lbl.text()
    assert "queue-job" not in dialog.details_lbl.text()


def test_repeated_refresh_details_calls_skip_describe_entirely(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_describe`'s own memoisation would hide a missing skip here -- a
    second call would still avoid re-reading the document by hitting the
    cache. What the early return in `_refresh_details` buys beyond that is
    not calling `_describe` (and re-stat'ing `is_dir()`) at all when the
    listing to show has not changed, so this spies on `_describe` itself
    rather than on what it reads.
    """
    _save(working_dir, "job")
    dialog = _open_dialog(qapp)
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))
    assert dialog.details_lbl.text() != ""

    calls: list[Any] = []
    real_describe = dialog._describe

    def counting_describe(listing: Any) -> str:
        calls.append(listing)
        return real_describe(listing)

    monkeypatch.setattr(dialog, "_describe", counting_describe)

    dialog._refresh_details()

    assert calls == []


def test_switching_back_to_a_previously_described_job_does_not_re_read_it(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The skip in `_refresh_details` only covers a listing unchanged since
    the last call -- switching away and back is a change each time, so it is
    `_describe`'s own memoisation, not the skip, that has to catch this.
    """
    _save(working_dir, "alpha", created_at="2026-01-01T00:00:00+00:00")
    _save(working_dir, "beta", created_at="2026-06-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)
    alpha_item = dialog.job_tree.findItems("alpha", Qt.MatchFlag.MatchExactly, 0)[0]
    beta_item = dialog.job_tree.findItems("beta", Qt.MatchFlag.MatchExactly, 0)[0]
    dialog.job_tree.setCurrentItem(alpha_item)
    dialog.job_tree.setCurrentItem(beta_item)

    calls: list[Path] = []
    real_load_job = load_job_dialog_module.load_job

    def counting_load_job(path: Path) -> Any:
        calls.append(path)
        return real_load_job(path)

    monkeypatch.setattr(load_job_dialog_module, "load_job", counting_load_job)

    dialog.job_tree.setCurrentItem(alpha_item)

    assert calls == []


def test_the_details_pane_escapes_html_in_a_job_s_name(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Job names are free text from a prompt, and the pane renders rich text.

    A name like this reaching the pane unescaped would inject markup into a
    QLabel that interprets it -- this plan has already had to fix that same
    class of bug twice, for the log pane and the save-confirmation box.
    """
    _save(working_dir, "<b>evil</b> & friends")
    dialog = _open_dialog(qapp)
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))

    text = dialog.details_lbl.text()
    assert "<b>evil</b>" not in text
    assert "&lt;b&gt;evil&lt;/b&gt; &amp; friends" in text


def test_a_retired_tracker_name_in_the_document_does_not_crash_the_pane(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """`tracker_image_hosts` is keyed by enum member name, so a tracker that
    has since been removed from `TrackerSelection` leaves a name the current
    build cannot resolve. Falling back to the raw string is what stops that
    from becoming an unhandled `ValueError` out of `_describe`.
    """
    job = store.build_job(
        "job",
        JobSummary(title="job"),
        {
            "shared_data": {
                "tracker_image_hosts": {
                    "RETIRED_TRACKER": {
                        "img_from": "IMAGES",
                        "img_to": "CHEVERETO_V3",
                        "img_to_type": "ImageHost",
                    }
                },
            }
        },
        config_profile="default",
    )
    store.save_job(job, working_dir)
    dialog = _open_dialog(qapp)
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))

    assert "RETIRED_TRACKER" in dialog.details_lbl.text()


def test_an_unreadable_job_does_not_break_the_details_pane(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = store.save_job(
        store.build_job(
            "broken", JobSummary(title="Broken"), {}, config_profile="default"
        ),
        working_dir,
    )
    (directory / store.JOB_DOCUMENT_NAME).write_text("not json", encoding="utf-8")
    dialog = _open_dialog(qapp)

    # listing skips unreadable jobs, so add the row by hand to exercise the pane
    from src.backend.jobs.models import JobListing

    listing = JobListing(
        job_id="x",
        name="broken",
        created_at="2026-01-01T00:00:00+00:00",
        summary=JobSummary(title="Broken"),
        path=directory,
        config_profile="default",
    )

    # The "Broken" title comes straight from the listing passed in, not from
    # the document -- it would show up even if load_job never ran at all. What
    # actually proves the corrupt document was read and its failure handled,
    # rather than this test silently exercising the happy path, is that
    # load_job's failure got logged.
    warnings: list[object] = []
    monkeypatch.setattr(
        load_job_dialog_module.LOG,
        "warning",
        lambda _source, message: warnings.append(message),
    )

    text = dialog._describe(listing)

    assert "Broken" in text
    assert warnings
    assert "not valid JSON" in str(warnings[0])


def test_the_open_folder_button_opens_the_selected_job_s_directory(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _save(working_dir, "job")
    dialog = _open_dialog(qapp)
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))
    assert dialog.open_folder_btn.isEnabled()

    opened: list[Path] = []
    monkeypatch.setattr(
        load_job_dialog_module, "open_explorer", lambda path: opened.append(path)
    )

    dialog.open_folder_btn.click()

    assert opened == [directory]


def test_renaming_rewrites_only_the_name(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _save(working_dir, "old name", trackers=["Aither"])
    dialog = _open_dialog(qapp)
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))
    dialog.job_tree.topLevelItem(0).setSelected(True)
    _answer_rename_prompt(monkeypatch, "new name")

    dialog._rename_selected()
    _wait_for_load(dialog, qapp)

    reloaded = store.load_job(directory)
    assert reloaded.name == "new name"
    assert reloaded.summary.trackers == ["Aither"]
    assert dialog.job_tree.topLevelItem(0).text(0) == "new name"


def test_a_failed_rename_reports_the_job_by_name(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delete's failure path names each job it could not remove -- see
    `test_one_failed_delete_does_not_strand_the_rest`. Rename's used to say
    only that "job" failed, leaving a user with several jobs open no way to
    tell which one broke.
    """
    _save(working_dir, "old name")
    dialog = _open_dialog(qapp)
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))
    dialog.job_tree.topLevelItem(0).setSelected(True)
    _answer_rename_prompt(monkeypatch, "new name")

    def flaky_write(*_a: Any, **_k: Any) -> None:
        raise load_job_dialog_module.JobStoreError("disk said no")

    monkeypatch.setattr(load_job_dialog_module, "write_job_document", flaky_write)
    reported: list[str] = []
    monkeypatch.setattr(
        load_job_dialog_module.QMessageBox,
        "critical",
        lambda _parent, _title, text, *_a, **_k: reported.append(text),
    )

    dialog._rename_selected()

    assert reported and "old name" in reported[0]


def test_a_rename_refreshes_the_cached_details_pane_text(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The details cache is keyed by path, and a rename keeps the same path --
    so a cache entry (or a "nothing changed" skip) left over from before the
    reload would go on showing the pre-rename name even though the row itself
    updated. Both are cleared in `_load_listings` for exactly this reason.
    """
    # A distinct title, so the pane's bolded name header -- what the cache is
    # actually keyed on and what rename actually changes -- is unambiguous
    # against the "Title" row it also shows, which rename leaves untouched.
    _save(working_dir, "old name", title="Some Movie")
    dialog = _open_dialog(qapp)
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))
    dialog.job_tree.topLevelItem(0).setSelected(True)
    assert "<b>old name</b>" in dialog.details_lbl.text()
    _answer_rename_prompt(monkeypatch, "new name")

    dialog._rename_selected()
    _wait_for_load(dialog, qapp)

    assert "<b>new name</b>" in dialog.details_lbl.text()
    assert "<b>old name</b>" not in dialog.details_lbl.text()


def test_renaming_a_queued_job_refreshes_its_queue_row_label(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_add_to_queue` binds the `JobListing` a queue item was queued with
    once, at add time, and nothing ever re-binds it. `_renumber_queue` builds
    each row's label from that stored object, so after renaming an
    already-queued job on disk, the queue row kept the old name -- the tree
    rebuilds on reload, but `_on_listings_loaded` never touched `queue_list`.
    Pre-existing, and made visible by T18 letting the user inspect a queue
    row at all.

    Asserted on the queue row's own text, not the tree's -- the tree already
    refreshed correctly before this fix, so checking it would not catch a
    queue row left stale.
    """
    _save(working_dir, "old name")
    dialog = _open_dialog(qapp)
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))
    dialog.job_tree.topLevelItem(0).setSelected(True)
    dialog._add_to_queue()
    assert dialog.queue_list.item(0).text() == "1. old name"
    _answer_rename_prompt(monkeypatch, "new name")

    dialog._rename_selected()
    _wait_for_load(dialog, qapp)

    assert dialog.queue_list.item(0).text() == "1. new name"


def test_cancelling_the_rename_changes_nothing(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _save(working_dir, "keep me")
    dialog = _open_dialog(qapp)
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))
    dialog.job_tree.topLevelItem(0).setSelected(True)
    _answer_rename_prompt(monkeypatch, "", accepted=False)

    dialog._rename_selected()
    _wait_for_load(dialog, qapp)

    assert store.load_job(directory).name == "keep me"


def test_an_empty_new_name_is_refused(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accepting the prompt with a blank field must not blank the job's name.

    Two things have to hold together: `_change_job_name` strips what was
    typed, and `_rename_selected` guards on `not accepted or not name`. Drop
    either -- the strip, or the second half of the guard -- and a user who
    clicks OK on a field holding only spaces writes `name: ""` to disk, with
    nothing failing. The cancel test only ever supplies `accepted=False`, so
    it cannot tell the halves of that guard apart. Whitespace is typed here
    rather than an empty string precisely so the strip is covered too.
    """
    directory = _save(working_dir, "keep me")
    dialog = _open_dialog(qapp)
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))
    dialog.job_tree.topLevelItem(0).setSelected(True)
    _answer_rename_prompt(monkeypatch, "   ")

    dialog._rename_selected()
    _wait_for_load(dialog, qapp)

    assert store.load_job(directory).name == "keep me"


def test_rename_targets_the_selected_job_not_the_current_row(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`currentItem()` can point at a row that is not selected.

    Ctrl+clicking a second row and ctrl+clicking it again leaves the current
    item there while the first row stays the only selection. Targeting the
    current row would rename the wrong job on disk while the right one is
    still highlighted.
    """
    keep_dir = _save(working_dir, "selected", created_at="2026-06-01T00:00:00+00:00")
    other_dir = _save(
        working_dir, "merely current", created_at="2026-01-01T00:00:00+00:00"
    )
    dialog = _open_dialog(qapp)

    selected_row = dialog.job_tree.topLevelItem(0)
    current_row = dialog.job_tree.topLevelItem(1)
    assert selected_row.text(0) == "selected"
    selected_row.setSelected(True)
    dialog.job_tree.setCurrentItem(
        current_row, 0, QItemSelectionModel.SelectionFlag.NoUpdate
    )
    assert dialog.job_tree.currentItem() is current_row
    assert [item.text(0) for item in dialog.job_tree.selectedItems()] == ["selected"]

    _answer_rename_prompt(monkeypatch, "renamed")

    dialog._rename_selected()
    _wait_for_load(dialog, qapp)

    assert store.load_job(keep_dir).name == "renamed"
    assert store.load_job(other_dir).name == "merely current"


def test_button_state_reflects_the_selected_job_not_the_current_row(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Same divergence as rename -- see
    `test_rename_targets_the_selected_job_not_the_current_row`. Enablement and
    the actions it gates have to agree on the same job, or a button that looks
    correctly enabled ends up acting on a row the user did not pick.
    """
    _save(working_dir, "selected", created_at="2026-06-01T00:00:00+00:00")
    _save(
        working_dir,
        "merely current",
        profile="other",
        created_at="2026-01-01T00:00:00+00:00",
    )
    dialog = _open_dialog(qapp)
    dialog.only_this_config.setChecked(False)

    selected_row = dialog.job_tree.topLevelItem(0)
    current_row = dialog.job_tree.topLevelItem(1)
    assert selected_row.text(0) == "selected"
    selected_row.setSelected(True)
    dialog.job_tree.setCurrentItem(
        current_row, 0, QItemSelectionModel.SelectionFlag.NoUpdate
    )
    assert dialog.job_tree.currentItem() is current_row
    assert [item.text(0) for item in dialog.job_tree.selectedItems()] == ["selected"]

    dialog._update_button_state()

    # "selected" matches the active profile: Load has to be enabled and
    # Switch has to stay off, even though the merely-current row is the one
    # that would need a switch.
    open_button = dialog.button_box.button(QDialogButtonBox.StandardButton.Open)
    assert open_button is not None
    assert open_button.isEnabled()
    assert not dialog.switch_btn.isEnabled()


def test_accept_selection_targets_the_selected_job_not_the_current_row(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Same divergence as rename -- see
    `test_rename_targets_the_selected_job_not_the_current_row` -- but worse: a
    listing loaded here lands on the process page, where the next action is
    Process. Loading the wrong release would upload it to a tracker.
    """
    selected_dir = _save(
        working_dir, "selected", created_at="2026-06-01T00:00:00+00:00"
    )
    other_dir = _save(
        working_dir, "merely current", created_at="2026-01-01T00:00:00+00:00"
    )
    dialog = _open_dialog(qapp)

    selected_row = dialog.job_tree.topLevelItem(0)
    current_row = dialog.job_tree.topLevelItem(1)
    assert selected_row.text(0) == "selected"
    selected_row.setSelected(True)
    dialog.job_tree.setCurrentItem(
        current_row, 0, QItemSelectionModel.SelectionFlag.NoUpdate
    )
    assert dialog.job_tree.currentItem() is current_row
    assert [item.text(0) for item in dialog.job_tree.selectedItems()] == ["selected"]

    dialog._accept_selection()

    assert dialog.selected_listing is not None
    assert dialog.selected_listing.path == selected_dir
    assert dialog.selected_listing.path != other_dir


def test_accept_selection_refuses_a_selected_cross_profile_job(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """The profile guard in `_accept_selection`, reached rather than assumed.

    With `only_this_config` checked -- its default -- a cross-profile row is
    hidden and deselected by `_apply_filter`, so `_selected_listings()` is
    empty and `_accept_selection` returns on `len(selected) != 1` before ever
    reaching the `matches_profile` check below it. Revealing and selecting
    the row is what it actually takes for a user to get a cross-profile job
    selected in the first place, so that is what reaches the guard this test
    means to cover.
    """
    _save(working_dir, "theirs", profile="anime")
    dialog = _open_dialog(qapp)
    dialog.only_this_config.setChecked(False)
    item = dialog.job_tree.topLevelItem(0)
    item.setSelected(True)
    # Confirm the selection actually landed, so a regression back to the
    # hidden-and-deselected state fails loudly here instead of the assertion
    # below passing for the wrong reason.
    assert len(dialog._selected_listings()) == 1

    dialog._accept_selection()

    assert dialog.selected_listing is None


def test_accept_with_switch_targets_the_selected_job_not_the_current_row(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Same divergence again, worse still: this drives `_switch_config_profile`,
    which calls `config.load_profile()` and emits `settings_refresh` --
    switching the active config, with its credentials and templates, on the
    strength of a row the user did not select.
    """
    selected_dir = _save(
        working_dir,
        "selected",
        profile="config-a",
        created_at="2026-06-01T00:00:00+00:00",
    )
    _save(
        working_dir,
        "merely current",
        profile="config-b",
        created_at="2026-01-01T00:00:00+00:00",
    )
    dialog = _open_dialog(qapp)
    dialog.only_this_config.setChecked(False)

    selected_row = dialog.job_tree.topLevelItem(0)
    current_row = dialog.job_tree.topLevelItem(1)
    assert selected_row.text(0) == "selected"
    selected_row.setSelected(True)
    dialog.job_tree.setCurrentItem(
        current_row, 0, QItemSelectionModel.SelectionFlag.NoUpdate
    )
    assert dialog.job_tree.currentItem() is current_row
    assert [item.text(0) for item in dialog.job_tree.selectedItems()] == ["selected"]

    dialog._accept_with_switch()

    assert dialog.switch_profile_requested is True
    assert dialog.selected_listing is not None
    assert dialog.selected_listing.path == selected_dir
    assert dialog.selected_listing.config_profile == "config-a"


def test_selection_hint_names_the_selected_job_not_the_current_row(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Same divergence as rename -- see
    `test_rename_targets_the_selected_job_not_the_current_row`. The hint is
    display-only, but it still has to describe the row that is actually
    highlighted, not whatever `currentItem()` last landed on.
    """
    _save(working_dir, "selected", created_at="2026-06-01T00:00:00+00:00")
    _save(
        working_dir,
        "merely current",
        profile="other",
        created_at="2026-01-01T00:00:00+00:00",
    )
    dialog = _open_dialog(qapp)
    dialog.only_this_config.setChecked(False)

    selected_row = dialog.job_tree.topLevelItem(0)
    current_row = dialog.job_tree.topLevelItem(1)
    assert selected_row.text(0) == "selected"
    selected_row.setSelected(True)
    dialog.job_tree.setCurrentItem(
        current_row, 0, QItemSelectionModel.SelectionFlag.NoUpdate
    )
    assert dialog.job_tree.currentItem() is current_row
    assert [item.text(0) for item in dialog.job_tree.selectedItems()] == ["selected"]

    # "selected" matches the active profile and is prepared, so the hint says
    # it is ready. The merely-current row is on another config -- if the hint
    # named it instead, this would talk about switching profiles, not loading.
    assert (
        dialog._selection_hint() == "'selected' is ready to load or add to the queue."
    )


def test_rename_is_only_available_for_one_job(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "one")
    _save(working_dir, "two")
    dialog = _open_dialog(qapp)
    dialog.job_tree.selectAll()

    assert not dialog.rename_btn.isEnabled()


def test_one_failed_delete_does_not_strand_the_rest(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Continuing past a failure is this method's whole point.

    An accidental `break`, or the `try` drifting outside the loop, would leave
    every job after the first failure sitting on disk while the user is told
    only about the one that failed. Nothing else in the suite would notice.
    """
    # Explicit timestamps, because the order matters: the failing job must be
    # processed FIRST for this test to catch a `break` after the failure. Left
    # to `_save`'s default both land in the same second, and `list_jobs` then
    # tie-breaks on the random shortuuid directory name -- so the guard would
    # only catch the mutation on roughly half of runs.
    fails_dir = _save(working_dir, "unlucky", created_at="2026-06-01T00:00:00+00:00")
    succeeds_dir = _save(working_dir, "fine", created_at="2026-01-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)
    dialog.job_tree.selectAll()
    assert dialog.job_tree.topLevelItem(0).text(0) == "unlucky"

    real_delete = load_job_dialog_module.delete_job

    def flaky(path: Path) -> None:
        if path == fails_dir:
            raise load_job_dialog_module.JobStoreError("disk said no")
        real_delete(path)

    reported: list[str] = []
    monkeypatch.setattr(load_job_dialog_module, "delete_job", flaky)
    monkeypatch.setattr(
        load_job_dialog_module.QMessageBox,
        "question",
        lambda *_a, **_k: load_job_dialog_module.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        load_job_dialog_module.QMessageBox,
        "critical",
        lambda _parent, _title, text, *_a, **_k: reported.append(text),
    )

    dialog._delete_selected()
    _wait_for_load(dialog, qapp)

    assert fails_dir.exists()
    assert not succeeds_dir.exists()
    assert reported and "unlucky" in reported[0]


# --------------------------------------------------------------------------
# the queue: an explicit, ordered list beside the tree
# --------------------------------------------------------------------------
def test_only_a_runnable_job_can_be_added_to_the_queue(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "ready", prepared=True)
    _save(working_dir, "not-ready", prepared=False)
    dialog = _open_dialog(qapp)
    dialog.job_tree.selectAll()

    assert not dialog.add_to_queue_btn.isEnabled()


def test_only_prepared_jobs_on_this_config_can_be_added_to_the_queue(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """A queue has nobody to answer a prompt, and no business using another
    config's credentials -- even calling `_add_to_queue` directly against a
    mixed selection (the button itself would be disabled first) must not let
    either kind in.
    """
    _save(working_dir, "ready", prepared=True, profile="config")
    _save(working_dir, "raw", prepared=False, profile="config")
    _save(working_dir, "other-config", prepared=True, profile="anime")
    dialog = _open_dialog(qapp, "config")
    dialog.only_this_config.setChecked(False)
    dialog.job_tree.selectAll()

    dialog._add_to_queue()

    assert [listing.name for listing in dialog.queueable_listings()] == ["ready"]


def test_adding_jobs_builds_a_queue_in_click_order(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Queue order must come from when each job was added, not from the
    tree's row order -- otherwise this would pass even if `_add_to_queue`
    silently re-sorted the queue to match the tree on every call.

    Newest-first sorting puts "second" at row 0 and "first" at row 1. Adding
    "first" (row 1) before "second" (row 0) makes the click order the exact
    reverse of the tree's display order, so only a queue that actually
    tracks add order -- not display order -- produces this sequence.
    """
    _save(working_dir, "first", created_at="2026-01-01T00:00:00+00:00")
    _save(working_dir, "second", created_at="2026-06-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)
    # `_load_listings` leaves row 0 selected as the initial current item;
    # clear it so only the row picked below is selected on the first add.
    dialog.job_tree.clearSelection()

    dialog.job_tree.topLevelItem(1).setSelected(True)
    dialog._add_to_queue()
    dialog.job_tree.clearSelection()
    dialog.job_tree.topLevelItem(0).setSelected(True)
    dialog._add_to_queue()

    assert [listing.name for listing in dialog.queueable_listings()] == [
        "first",
        "second",
    ]


def test_a_job_cannot_be_queued_twice(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "once")
    dialog = _open_dialog(qapp)
    dialog.job_tree.topLevelItem(0).setSelected(True)

    dialog._add_to_queue()
    dialog._add_to_queue()

    assert dialog.queue_list.count() == 1


def test_a_queued_job_can_be_moved_up(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Asserts the resulting sequence, not merely that the current row moved.

    "a" and "b" are queued in tree row order ("b" first, since newest-first
    sorting puts it at row 0), giving a starting queue of ["b", "a"]. Moving
    "a" up must produce ["a", "b"] -- which matches neither that add order
    nor the tree's display order, so it cannot pass by coincidence.
    """
    _save(working_dir, "a", created_at="2026-01-01T00:00:00+00:00")
    _save(working_dir, "b", created_at="2026-06-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)
    dialog.job_tree.topLevelItem(0).setSelected(True)
    dialog._add_to_queue()
    dialog.job_tree.clearSelection()
    dialog.job_tree.topLevelItem(1).setSelected(True)
    dialog._add_to_queue()
    dialog.queue_list.setCurrentRow(1)

    dialog._move_queued(-1)

    assert dialog.queue_list.currentRow() == 0
    assert [listing.name for listing in dialog.queueable_listings()] == ["a", "b"]


def test_removing_from_the_queue_leaves_the_job_saved(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    directory = _save(working_dir, "keep")
    dialog = _open_dialog(qapp)
    dialog.job_tree.topLevelItem(0).setSelected(True)
    dialog._add_to_queue()
    dialog.queue_list.setCurrentRow(0)

    dialog._remove_queued()

    assert dialog.queue_list.count() == 0
    assert directory.exists()


def test_run_queue_needs_a_queue(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "ready")
    dialog = _open_dialog(qapp)

    assert not dialog.queue_btn.isEnabled()

    dialog.job_tree.topLevelItem(0).setSelected(True)
    dialog._add_to_queue()

    assert dialog.queue_btn.isEnabled()


def test_adding_prepared_jobs_enables_the_queue_and_accept_queue_reports_them(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "ready-one", prepared=True, profile="config")
    _save(working_dir, "ready-two", prepared=True, profile="config")
    dialog = _open_dialog(qapp, "config")
    dialog.job_tree.selectAll()

    dialog._add_to_queue()

    assert dialog.queue_btn.isEnabled()

    dialog._accept_queue()

    assert {listing.name for listing in dialog.queued_listings} == {
        "ready-one",
        "ready-two",
    }
    assert dialog.selected_listing is None


def test_deleting_a_queued_job_takes_it_out_of_the_queue(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asserts the queue shrank AND that an unrelated queued job survived --
    otherwise this would still pass a `_drop_from_queue` that emptied the
    whole queue on any delete, rather than only the deleted job's entry.
    """
    _save(working_dir, "doomed", created_at="2026-01-01T00:00:00+00:00")
    _save(working_dir, "survivor", created_at="2026-06-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)
    dialog.job_tree.selectAll()
    dialog._add_to_queue()
    doomed_item = dialog.job_tree.findItems("doomed", Qt.MatchFlag.MatchExactly, 0)[0]
    dialog.job_tree.clearSelection()
    doomed_item.setSelected(True)
    monkeypatch.setattr(
        load_job_dialog_module.QMessageBox,
        "question",
        lambda *_a, **_k: load_job_dialog_module.QMessageBox.StandardButton.Yes,
    )

    dialog._delete_selected()
    _wait_for_load(dialog, qapp)

    assert dialog.queue_list.count() == 1
    assert [listing.name for listing in dialog.queueable_listings()] == ["survivor"]


def test_a_failed_delete_leaves_its_queue_entry_in_place(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delete that raises must not also drop its queue entry -- the job is
    untouched on disk and still perfectly runnable, so losing its queue
    position would be an undisclosed side effect of an operation that never
    happened. Only the job whose delete actually succeeded should leave the
    queue.
    """
    stuck_dir = _save(working_dir, "stuck", created_at="2026-01-01T00:00:00+00:00")
    _save(working_dir, "goes", created_at="2026-06-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)
    dialog.job_tree.selectAll()
    dialog._add_to_queue()

    real_delete = load_job_dialog_module.delete_job

    def flaky(path: Path) -> None:
        if path == stuck_dir:
            raise load_job_dialog_module.JobStoreError("disk said no")
        real_delete(path)

    reported: list[str] = []
    monkeypatch.setattr(load_job_dialog_module, "delete_job", flaky)
    monkeypatch.setattr(
        load_job_dialog_module.QMessageBox,
        "question",
        lambda *_a, **_k: load_job_dialog_module.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        load_job_dialog_module.QMessageBox,
        "critical",
        lambda _parent, _title, text, *_a, **_k: reported.append(text),
    )

    dialog._delete_selected()
    _wait_for_load(dialog, qapp)

    assert [listing.name for listing in dialog.queueable_listings()] == ["stuck"]
    assert reported and "stuck" in reported[0]


# --------------------------------------------------------------------------
# T18 fix round 2: queue-management sites left unguarded by round 1
# --------------------------------------------------------------------------
def test_removing_a_queued_job_does_not_steal_the_pane_from_the_tree(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """`_remove_queued` calls `takeItem` on the queue's current row, which
    fires `currentRowChanged` -- that is queue bookkeeping, not the user
    picking the queue pane, so it must not set the source. Two jobs are
    queued so one remains after the removal: the source has to keep
    describing the tree rather than the fallback in `_details_listing`
    papering over an empty queue, which would mask this bug.
    """
    _save(working_dir, "queued-a", created_at="2026-01-01T00:00:00+00:00")
    _save(working_dir, "queued-b", created_at="2026-02-01T00:00:00+00:00")
    _save(working_dir, "tree-job", created_at="2026-06-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)
    a_item = dialog.job_tree.findItems("queued-a", Qt.MatchFlag.MatchExactly, 0)[0]
    b_item = dialog.job_tree.findItems("queued-b", Qt.MatchFlag.MatchExactly, 0)[0]
    tree_item = dialog.job_tree.findItems("tree-job", Qt.MatchFlag.MatchExactly, 0)[0]

    _click_tree_item(dialog, a_item, qapp)
    dialog._add_to_queue()
    _click_tree_item(dialog, b_item, qapp)
    dialog._add_to_queue()

    _click_queue_row(dialog, 0, qapp)
    _click_tree_item(dialog, tree_item, qapp)
    assert dialog._details_source == "tree"
    assert "tree-job" in dialog.details_lbl.text()

    dialog.queue_remove_btn.click()

    assert dialog._details_source == "tree"
    assert "tree-job" in dialog.details_lbl.text()


def test_moving_a_queued_job_does_not_steal_the_pane_from_the_tree(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """`_move_queued` calls `takeItem` and `setCurrentRow` on the queue,
    either of which can fire `currentRowChanged` -- reordering the queue is
    not the user picking the queue pane.
    """
    _save(working_dir, "queued-a", created_at="2026-01-01T00:00:00+00:00")
    _save(working_dir, "queued-b", created_at="2026-02-01T00:00:00+00:00")
    _save(working_dir, "tree-job", created_at="2026-06-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)
    a_item = dialog.job_tree.findItems("queued-a", Qt.MatchFlag.MatchExactly, 0)[0]
    b_item = dialog.job_tree.findItems("queued-b", Qt.MatchFlag.MatchExactly, 0)[0]
    tree_item = dialog.job_tree.findItems("tree-job", Qt.MatchFlag.MatchExactly, 0)[0]

    _click_tree_item(dialog, a_item, qapp)
    dialog._add_to_queue()
    _click_tree_item(dialog, b_item, qapp)
    dialog._add_to_queue()

    _click_queue_row(dialog, 1, qapp)
    _click_tree_item(dialog, tree_item, qapp)
    assert dialog._details_source == "tree"
    assert "tree-job" in dialog.details_lbl.text()

    dialog.queue_up_btn.click()

    assert dialog._details_source == "tree"
    assert "tree-job" in dialog.details_lbl.text()


def test_deleting_a_queued_job_does_not_steal_the_pane_from_the_tree(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_drop_from_queue` also calls `takeItem` on the queue -- deleting a
    different job that happens to be queued must not flip the source away
    from whatever the user was actually looking at in the tree.
    """
    _save(working_dir, "queued-a", created_at="2026-01-01T00:00:00+00:00")
    _save(working_dir, "queued-b", created_at="2026-02-01T00:00:00+00:00")
    _save(working_dir, "tree-job", created_at="2026-06-01T00:00:00+00:00")
    dialog = _open_dialog(qapp)
    a_item = dialog.job_tree.findItems("queued-a", Qt.MatchFlag.MatchExactly, 0)[0]
    b_item = dialog.job_tree.findItems("queued-b", Qt.MatchFlag.MatchExactly, 0)[0]
    tree_item = dialog.job_tree.findItems("tree-job", Qt.MatchFlag.MatchExactly, 0)[0]

    _click_tree_item(dialog, a_item, qapp)
    dialog._add_to_queue()
    _click_tree_item(dialog, b_item, qapp)
    dialog._add_to_queue()

    _click_queue_row(dialog, 0, qapp)
    _click_tree_item(dialog, tree_item, qapp)
    assert dialog._details_source == "tree"

    dialog.job_tree.clearSelection()
    a_item.setSelected(True)
    monkeypatch.setattr(
        load_job_dialog_module.QMessageBox,
        "question",
        lambda *_a, **_k: load_job_dialog_module.QMessageBox.StandardButton.Yes,
    )

    dialog._delete_selected()
    _wait_for_load(dialog, qapp)

    assert dialog._details_source == "tree"
    assert "tree-job" in dialog.details_lbl.text()
    assert "queued-b" not in dialog.details_lbl.text()


def test_reloading_while_the_queue_is_the_source_does_not_steal_the_pane(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_load_listings` clears the tree synchronously, before the async
    reload it kicks off even produces anything to show -- that clear is what
    actually flips the source first during a real rename/delete reload, not
    `_on_listings_loaded`'s own (already-empty-by-then) clear. Disclosed as
    untested in the T18 fix round 1 report; this closes that gap.

    Also pins the rebound queue listing's rendered text, not just the
    source: renaming keeps the same path, and a stale `_details_cache` entry
    or `_last_described_path` left over from a button-state refresh that ran
    mid-reload (while the tree was empty and the queue not yet rebound)
    would otherwise go on showing the pre-rename name even after the source
    correctly stayed "queue".
    """
    _save(working_dir, "queued-job")
    dialog = _open_dialog(qapp)
    item = dialog.job_tree.topLevelItem(0)
    _click_tree_item(dialog, item, qapp)
    dialog._add_to_queue()

    _click_queue_row(dialog, 0, qapp)
    assert dialog._details_source == "queue"
    assert "queued-job" in dialog.details_lbl.text()

    _answer_rename_prompt(monkeypatch, "renamed-job")
    dialog._rename_selected()
    _wait_for_load(dialog, qapp)

    assert dialog._details_source == "queue"
    assert "renamed-job" in dialog.details_lbl.text()


# --------------------------------------------------------------------------
# loading is asynchronous
# --------------------------------------------------------------------------
def test_the_list_starts_empty_and_says_it_is_loading(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Constructing the dialog must not block on `list_jobs` -- that call is
    what stalls visibly on a network share, so the tree has to start empty
    with a placeholder rather than already populated.
    """
    _save(working_dir, "job")
    dialog = LoadJobDialog("default")

    assert dialog.job_tree.topLevelItemCount() == 0
    assert "Loading" in dialog.empty_lbl.text()
    assert dialog.empty_lbl.isVisible() or not dialog.isVisible()

    # Nothing above depends on this: it only lets the loader thread `__init__`
    # started finish before `dialog` goes out of scope. Destroying a `QThread`
    # while it is still running aborts the process, not just this test.
    _wait_for_load(dialog, qapp)


def test_listings_populate_the_tree_when_they_arrive(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "job")
    dialog = LoadJobDialog("default")

    _wait_for_load(dialog, qapp)

    assert dialog.job_tree.topLevelItemCount() == 1
    assert dialog.job_tree.topLevelItem(0).text(0) == "job"


def test_an_empty_working_directory_reports_no_jobs(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    dialog = LoadJobDialog("default")

    _wait_for_load(dialog, qapp)

    assert "No saved jobs yet" in dialog.empty_lbl.text()


def test_closing_mid_load_waits_for_the_loader_before_tearing_down(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_stop_loader` exists purely because destroying a running `QThread`
    aborts the process outright, so what needs proving is that closing the
    dialog actually blocks until the loader has finished -- not merely that
    `reject()` did not raise, and not only up to some cap.

    The 2.2s sleep here (on the loader's own OS thread, so it does not block
    this test) is deliberately past the two-second bound an earlier version
    of `_stop_loader` used: that cap failed in exactly the slow-network-share
    scan this task exists to get off the GUI thread, since that is precisely
    the case that runs long. The fix has no cap, and this is what proves it
    -- a version with `wait(2000)` reinstated fails this test, since the
    loader would still be asleep for another ~200ms when the assertion runs.
    """
    _save(working_dir, "job")
    original_run = load_job_dialog_module._ListingLoader.run

    def slow_run(self: Any) -> None:
        time.sleep(2.2)
        original_run(self)

    monkeypatch.setattr(load_job_dialog_module._ListingLoader, "run", slow_run)

    dialog = LoadJobDialog("default")
    loader = dialog._loader
    assert loader is not None
    assert loader.isRunning()

    dialog.reject()

    # `_stop_loader` clears `dialog._loader` before returning, so the loader
    # reference captured above -- not `dialog._loader`, which is now `None`
    # -- is what proves the thread itself finished rather than merely being
    # detached.
    assert loader.isRunning() is False
    # And if the disconnect happened after (or not at all), the loader's
    # `loaded` signal -- queued for delivery once the sleep ends -- would
    # still land on a dialog that is closing, repopulating a tree nobody is
    # looking at.
    qapp.processEvents()
    assert dialog.job_tree.topLevelItemCount() == 0


def test_calling_load_listings_twice_retires_the_first_loader(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second `_load_listings()` call while the first is still scanning
    must retire that first loader, not orphan it. An orphaned loader is still
    running and still parented to the dialog, but no longer reachable through
    `self._loader` -- which is exactly the thread `done()` could never wait
    on, and destroying it later aborts the process.

    Slowing only the first `run()` (via a call counter) guarantees the first
    loader is still going when the second call arrives, rather than hoping a
    fast local scan wins a race.
    """
    _save(working_dir, "job")
    original_run = load_job_dialog_module._ListingLoader.run
    calls = 0

    def slow_first_run(self: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            time.sleep(0.4)
        original_run(self)

    monkeypatch.setattr(load_job_dialog_module._ListingLoader, "run", slow_first_run)

    dialog = LoadJobDialog("default")
    first_loader = dialog._loader
    assert first_loader is not None
    assert first_loader.isRunning()

    dialog._load_listings()

    # Retired, not abandoned: if `_load_listings` had merely rebound
    # `self._loader` to a new instance, `first_loader` would still be
    # running here.
    assert first_loader.isRunning() is False
    assert dialog._loader is not None
    assert dialog._loader is not first_loader

    _wait_for_load(dialog, qapp)

    assert dialog.job_tree.topLevelItemCount() == 1
    assert dialog.job_tree.topLevelItem(0).text(0) == "job"


def test_stop_loader_tolerates_a_loader_whose_c_plus_plus_object_is_gone(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """`wait()` on a `QThread` whose underlying C++ object is already
    destroyed raises `RuntimeError`, which is exactly the post-condition
    `_stop_loader` wants -- no live thread left to wait for -- so it has to
    be tolerated rather than propagate out of dialog close.

    Not reachable through the real `_ListingLoader` today, and there is no
    safe way to actually destroy a live `QThread`'s C++ object from Python to
    reproduce it -- doing so aborts the process rather than raising. A stub
    whose `wait()` raises `RuntimeError` stands in for that case instead.
    """
    dialog = _open_dialog(qapp)

    def raise_runtime_error() -> None:
        raise RuntimeError("Internal C++ object already deleted.")

    dialog._loader = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        loaded=SimpleNamespace(disconnect=lambda *_a, **_k: None),
        wait=raise_runtime_error,
    )

    dialog._stop_loader()

    assert dialog._loader is None


# --------------------------------------------------------------------------
# _saved_text: renders the stored UTC timestamp in local time for the
# "Saved" column and the details pane. Local time is not controllable
# cross-platform in this test suite (no `time.tzset()` on Windows), so these
# assertions are written to hold regardless of the runner's zone rather than
# pinning a literal rendered string.
# --------------------------------------------------------------------------


def test_saved_text_format_is_pinned() -> None:
    rendered = LoadJobDialog._saved_text("2026-01-01T00:00:00+00:00")

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", rendered)


def test_saved_text_preserves_the_instant() -> None:
    """Timezone-independent: compares the instant the rendering represents
    against the instant that went in, not the wall-clock text -- which would
    only match on a UTC runner. The one-minute tolerance is because the
    format drops seconds.
    """
    raw = "2026-01-01T00:00:00+00:00"

    rendered = LoadJobDialog._saved_text(raw)

    parsed = datetime.strptime(rendered, "%Y-%m-%d %H:%M").astimezone()
    assert abs((parsed - datetime.fromisoformat(raw)).total_seconds()) < 60


def test_saved_text_falls_back_to_the_input_verbatim_when_unparseable() -> None:
    assert LoadJobDialog._saved_text("not a date") == "not a date"


def test_a_chevereto_instance_destination_renders_as_its_kind(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """`img_to_type` says `ImageHostRef` since Chevereto went multi-instance.
    The pane cannot name the site (the archive stores the instance id, and the
    label lives in a config profile this listing spans several of), but it must
    still resolve the kind rather than fall through to the raw member name."""
    job = store.build_job(
        "Instanced",
        JobSummary(title="Instanced", year=2021, trackers=["Aither"]),
        {
            "shared_data": {
                "loaded_images": ["a.png"],
                "tracker_image_hosts": {
                    "AITHER": {
                        "img_from": "IMAGES",
                        "img_to": "CHEVERETO_V4",
                        "img_to_type": "ImageHostRef",
                        "img_to_instance": "5f2c9a1e",
                    }
                },
            }
        },
        config_profile="default",
    )
    job.created_at = "2021-01-01T00:00:00+00:00"
    store.save_job(job, working_dir)

    dialog = _open_dialog(qapp)
    item = dialog.job_tree.findItems("Instanced", Qt.MatchFlag.MatchExactly, 0)[0]
    dialog.job_tree.setCurrentItem(item)

    text = dialog.details_lbl.text()
    assert "Chevereto v4" in text
    assert "CHEVERETO_V4" not in text
