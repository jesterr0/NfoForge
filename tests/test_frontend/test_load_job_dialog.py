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


def test_the_list_opens_sorted_newest_first(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Assert the sort is configured, not that the rows happen to be in order.

    `list_jobs` already returns newest-first, so checking row 0 proves nothing
    -- it passes with sorting switched off entirely. The sort indicator is what
    only `sortByColumn` can set.
    """
    _save(working_dir, "older", created_at="2026-01-01T00:00:00+00:00")
    _save(working_dir, "newer", created_at="2026-06-01T00:00:00+00:00")
    dialog = LoadJobDialog("default")

    header = dialog.job_tree.header()
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
    dialog = LoadJobDialog("default")

    dialog.job_tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    assert [
        dialog.job_tree.topLevelItem(index).text(0)
        for index in range(dialog.job_tree.topLevelItemCount())
    ] == ["alpha", "zulu"]


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


def test_filtering_matches_name_title_and_tracker(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "alpha", title="Alpha Movie", trackers=["Aither"])
    _save(working_dir, "beta", title="Beta Movie", trackers=["Huno"])
    dialog = LoadJobDialog("default")

    dialog.filter_edit.setText("huno")

    visible = [
        dialog.job_tree.topLevelItem(i).text(0)
        for i in range(dialog.job_tree.topLevelItemCount())
        if not dialog.job_tree.topLevelItem(i).isHidden()
    ]
    assert visible == ["beta"]


def test_only_this_config_hides_other_profiles_by_default(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "mine", profile="default")
    _save(working_dir, "theirs", profile="anime")
    dialog = LoadJobDialog("default")

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
    dialog = LoadJobDialog("default")

    dialog.only_this_config.setChecked(False)

    assert not dialog.job_tree.topLevelItem(0).isHidden()


def test_hiding_a_row_also_deselects_it(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """A hidden row left selected would silently take part in Load or Delete."""
    _save(working_dir, "alpha")
    dialog = LoadJobDialog("default")
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
    dialog = LoadJobDialog("default")
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
    _save(working_dir, "ready", prepared=True)
    _save(working_dir, "not-ready", prepared=False)
    dialog = LoadJobDialog("default")
    dialog.job_tree.selectAll()

    assert not dialog.queue_btn.isEnabled()
    assert "not prepared" in dialog.status_lbl.text()


def test_a_cross_profile_selection_says_which_config_it_needs(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "theirs", profile="anime")
    dialog = LoadJobDialog("default")
    dialog.only_this_config.setChecked(False)
    dialog.job_tree.topLevelItem(0).setSelected(True)
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))

    assert "anime" in dialog.status_lbl.text()


def test_double_clicking_a_cross_profile_row_offers_the_switch(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Silently doing nothing is the current behaviour and the worst option."""
    _save(working_dir, "theirs", profile="anime")
    dialog = LoadJobDialog("default")
    dialog.only_this_config.setChecked(False)
    item = dialog.job_tree.topLevelItem(0)
    dialog.job_tree.setCurrentItem(item)

    dialog._on_double_click(item, 0)

    assert dialog.switch_profile_requested is True
    assert dialog.selected_listing is not None


def test_state_column_carries_an_icon(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save(working_dir, "job", prepared=True)
    dialog = LoadJobDialog("default")

    assert not dialog.job_tree.topLevelItem(0).icon(5).isNull()


def test_the_state_icon_is_chosen_by_the_job_s_own_state(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """A non-null icon on one row proves only that *an* icon was set.

    Setting the same icon on every row unconditionally would satisfy that, so
    what pins the conditional is the two states resolving to different icons.
    `QIcon.cacheKey()` is equal for references to one icon and differs between
    distinct ones, which is exactly the distinction needed here.
    """
    _save(working_dir, "ready", prepared=True)
    _save(working_dir, "draft", prepared=False)
    dialog = LoadJobDialog("default")

    rows = {
        dialog.job_tree.topLevelItem(index).text(0): dialog.job_tree.topLevelItem(index)
        for index in range(dialog.job_tree.topLevelItemCount())
    }
    ready_icon = rows["ready"].icon(5)
    draft_icon = rows["draft"].icon(5)

    assert not ready_icon.isNull()
    assert not draft_icon.isNull()
    assert ready_icon.cacheKey() != draft_icon.cacheKey()


def test_delete_removes_every_selected_job(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save(working_dir, "one")
    _save(working_dir, "two")
    dialog = LoadJobDialog("default")
    dialog.job_tree.selectAll()
    monkeypatch.setattr(
        load_job_dialog_module.QMessageBox,
        "question",
        lambda *_a, **_k: load_job_dialog_module.QMessageBox.StandardButton.Yes,
    )

    dialog._delete_selected()

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
    dialog = LoadJobDialog("default")
    item = dialog.job_tree.findItems("remove", Qt.MatchFlag.MatchExactly, 0)[0]
    item.setSelected(True)
    monkeypatch.setattr(
        load_job_dialog_module.QMessageBox,
        "question",
        lambda *_a, **_k: load_job_dialog_module.QMessageBox.StandardButton.Yes,
    )

    dialog._delete_selected()

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
    dialog = LoadJobDialog("default")
    dialog.job_tree.selectAll()
    asked: list[str] = []

    def capture(_parent: Any, _title: str, text: str, *_a: Any, **_k: Any) -> Any:
        asked.append(text)
        return load_job_dialog_module.QMessageBox.StandardButton.No

    monkeypatch.setattr(load_job_dialog_module.QMessageBox, "question", capture)

    dialog._delete_selected()

    assert "alpha" in asked[0] and "beta" in asked[0]


def test_the_delete_key_is_wired_to_delete(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    dialog = LoadJobDialog("default")

    assert dialog.delete_btn.shortcut() == Qt.Key.Key_Delete


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
    dialog = LoadJobDialog("default")

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

    dialog = LoadJobDialog("default")
    item = dialog.job_tree.findItems("Example", Qt.MatchFlag.MatchExactly, 0)[0]
    dialog.job_tree.setCurrentItem(item)

    text = dialog.details_lbl.text()
    assert "Example" in text
    assert "Aither" in text
    assert "CHEVERETO_V3" in text
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
    dialog = LoadJobDialog("default")

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
    dialog = LoadJobDialog("default")
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))
    assert dialog.details_lbl.text() != ""
    assert dialog.open_folder_btn.isEnabled()

    dialog.filter_edit.setText("nothing matches this")

    assert dialog.details_lbl.text() == ""
    assert not dialog.open_folder_btn.isEnabled()


def test_the_details_pane_escapes_html_in_a_job_s_name(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Job names are free text from a prompt, and the pane renders rich text.

    A name like this reaching the pane unescaped would inject markup into a
    QLabel that interprets it -- this plan has already had to fix that same
    class of bug twice, for the log pane and the save-confirmation box.
    """
    _save(working_dir, "<b>evil</b> & friends")
    dialog = LoadJobDialog("default")
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
    dialog = LoadJobDialog("default")
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
    dialog = LoadJobDialog("default")

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
    dialog = LoadJobDialog("default")
    dialog.job_tree.setCurrentItem(dialog.job_tree.topLevelItem(0))
    assert dialog.open_folder_btn.isEnabled()

    opened: list[Path] = []
    monkeypatch.setattr(
        load_job_dialog_module, "open_explorer", lambda path: opened.append(path)
    )

    dialog.open_folder_btn.click()

    assert opened == [directory]


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
    dialog = LoadJobDialog("default")
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

    assert fails_dir.exists()
    assert not succeeds_dir.exists()
    assert reported and "unlucky" in reported[0]
