"""Coverage for saving a job and resuming it at the process page."""

from pathlib import Path
import struct
from types import SimpleNamespace
from typing import Any, cast
import wave

from pymediainfo import MediaInfo
from PySide6.QtWidgets import (
    QDialog,
    QMessageBox,
    QPushButton,
    QWizard,
    QWizardPage,
)
import pytest

from src.backend.jobs import (
    context_from_dict,
    context_to_dict,
    store,
    template_fingerprint,
)
from src.backend.jobs.models import JobSummary
from src.backend.upload_retry import TrackerRunOutcome
from src.context.processing_context import ProcessingContext
from src.enums.image_host import ImageHost, ImageSource
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.upload_process import UploadProcessMode
from src.enums.wizard import WizardPages
from src.frontend.custom_widgets import load_job_dialog as load_job_dialog_module
from src.frontend.custom_widgets.combo_qtree import ComboBoxTreeWidget
from src.frontend.custom_widgets.load_job_dialog import LoadJobDialog
from src.frontend.wizards import process as process_module
from src.frontend.wizards.process import ProcessPage
from src.frontend.wizards.wizard import MainWindowWizard
from src.packages.custom_types import ImageUploadFromTo
from src.payloads.image_hosts import ImagePayloadBase


@pytest.fixture
def working_dir(tmp_path: Path) -> Path:
    return tmp_path / "nfoforge"


@pytest.fixture
def patched_working_dirs(working_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the picker's profile scan at the test's working directory."""
    monkeypatch.setattr(
        load_job_dialog_module, "unique_working_dirs", lambda: [working_dir]
    )


@pytest.fixture
def sample_media(tmp_path: Path) -> Path:
    path = tmp_path / "Example.Movie.2024.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(struct.pack("<" + "h" * 2400, *([0] * 2400)))
    return path


def _populate(context: ProcessingContext, media: Path) -> None:
    media_input = context.media_input
    media_input.input_path = media
    media_input.media_type = MediaType.MOVIE
    media_input.working_dir = media.parent / "working"
    media_input.file_list.append(media)
    media_input.file_list_mediainfo[media] = MediaInfo.parse(
        media, legacy_stream_display=True
    )

    context.media_search.media_type = MediaType.MOVIE
    context.media_search.title = "Example"
    context.media_search.year = 2024

    shared = context.shared_data
    shared.selected_trackers = [TrackerSelection.AITHER]
    shared.loaded_images = [media.parent / "img1.png"]
    shared.generated_images = True
    shared.tracker_image_hosts[TrackerSelection.AITHER] = ImageUploadFromTo(
        ImageSource.IMAGES, ImageHost.CHEVERETO_V3
    )


def _wizard_stub(
    *, upload_enabled: bool = True, nfo_template: str | None = None
) -> Any:
    """A real QWizard (needed as a QMessageBox parent) with a stub config.

    `MainWindowWizard` needs a live `MainWindow` to construct, so its methods
    are exercised unbound here, the same way the sibling page tests do.
    """
    wizard = QWizard()
    wizard.config = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        settings=SimpleNamespace(
            trackers=SimpleNamespace(
                by_selection=lambda: {
                    TrackerSelection.AITHER: SimpleNamespace(
                        upload_enabled=upload_enabled, nfo_template=nfo_template
                    )
                }
            )
        )
    )
    wizard._confirm_profile_can_serve_job = (  # pyright: ignore[reportAttributeAccessIssue]
        lambda job_name, context: MainWindowWizard._confirm_profile_can_serve_job(
            wizard, job_name, context
        )
    )
    wizard._stale_template_warnings = (  # pyright: ignore[reportAttributeAccessIssue]
        MainWindowWizard._stale_template_warnings
    )
    return wizard


def _fake_page(context: ProcessingContext, *, last_used: dict | None = None) -> Any:
    """Duck-typed `ProcessPage` stand-in, as used in the sibling page tests."""
    page = SimpleNamespace(
        context=context,
        processing_mode=UploadProcessMode.DUPE_CHECK,
        save_config=False,
        tracker_process_tree=ComboBoxTreeWidget(
            headers=("Tracker", "Image Host", "Status")
        ),
        config=SimpleNamespace(
            settings=SimpleNamespace(
                general=SimpleNamespace(enable_plugins=False),
                plugins=SimpleNamespace(image_host_uploader=None),
                image_hosts=SimpleNamespace(
                    by_selection=lambda: {
                        ImageHost.CHEVERETO_V3: ImagePayloadBase(
                            base_url="https://example.test", enabled=True
                        ),
                        ImageHost.PIXHOST: ImagePayloadBase(
                            base_url="https://pix.test", enabled=True
                        ),
                    }
                ),
                trackers=SimpleNamespace(
                    order=list(TrackerSelection),
                    last_used_image_host=last_used if last_used is not None else {},
                ),
            ),
            plugin_manager=None,
        ),
    )
    page._image_host_label = ProcessPage._image_host_label
    page._plugin_image_host_available = lambda: False
    page._sync_tracker_image_hosts = lambda: ProcessPage._sync_tracker_image_hosts(page)
    page._tree_combo_changed = lambda combo, idx: ProcessPage._tree_combo_changed(
        page, combo, idx
    )
    # wired the same way `ProcessPage.__init__` wires it: without this the
    # fake page never exercises the signal path that `add_tracker_items` (via
    # `ComboBoxTreeWidget.add_row` -> `add_combobox_to_row`) fires mid-construction
    page.tracker_process_tree.combo_changed.connect(page._tree_combo_changed)
    return page


# --------------------------------------------------------------------------
# save -> load -> restore
# --------------------------------------------------------------------------
def test_saved_job_round_trips_through_the_store(
    sample_media: Path, working_dir: Path
) -> None:
    source = ProcessingContext()
    _populate(source, sample_media)

    job = store.build_job(
        name="Example (2024)",
        summary=JobSummary(title="Example", year=2024, trackers=["Aither"]),
        context=context_to_dict(source),
        config_profile="config",
    )
    path = store.save_job(job, working_dir)

    restored = ProcessingContext()
    context_from_dict(store.load_job(path).context, restored)

    assert restored.media_input.input_path == sample_media
    assert restored.shared_data.selected_trackers == [TrackerSelection.AITHER]
    assert restored.shared_data.tracker_image_hosts == {
        TrackerSelection.AITHER: ImageUploadFromTo(
            ImageSource.IMAGES, ImageHost.CHEVERETO_V3
        )
    }
    assert restored.media_input.require_mediainfo(sample_media).tracks


# --------------------------------------------------------------------------
# process page repopulation
# --------------------------------------------------------------------------
def test_restored_image_host_wins_over_the_last_used_preference(
    qapp: Any, sample_media: Path
) -> None:
    """A resumed job must reinstate its own choice, not the global default."""
    context = ProcessingContext()
    _populate(context, sample_media)
    page = _fake_page(
        context,
        last_used={TrackerSelection.AITHER: ImageHost.PIXHOST},
    )

    ProcessPage.add_tracker_items(page)

    assert context.shared_data.tracker_image_hosts == {
        TrackerSelection.AITHER: ImageUploadFromTo(
            ImageSource.IMAGES, ImageHost.CHEVERETO_V3
        )
    }


def test_last_used_preference_still_applies_to_a_fresh_run(
    qapp: Any, sample_media: Path
) -> None:
    context = ProcessingContext()
    _populate(context, sample_media)
    context.shared_data.tracker_image_hosts.clear()
    page = _fake_page(context, last_used={TrackerSelection.AITHER: ImageHost.PIXHOST})

    ProcessPage.add_tracker_items(page)

    assert (
        context.shared_data.tracker_image_hosts[TrackerSelection.AITHER].img_to
        is ImageHost.PIXHOST
    )


def test_a_tracker_with_no_screenshots_only_offers_disabled_and_does_not_crash(
    qapp: Any, sample_media: Path
) -> None:
    """Regression guard: a tracker that needs no images (nothing generated,
    no URLs supplied) still builds a row, whose combo has exactly one entry
    (Disabled). Adding that single entry is what triggers the
    `combo_changed` signal mid-construction (see test_combo_qtree.py), and it
    used to crash unpacking `get_item_values()` before the row's own combo
    box was in `combo_box_map`."""
    context = ProcessingContext()
    _populate(context, sample_media)
    context.shared_data.loaded_images = None
    context.shared_data.generated_images = False
    context.shared_data.url_data.clear()
    context.shared_data.tracker_image_hosts.clear()
    page = _fake_page(context)

    ProcessPage.add_tracker_items(page)

    assert context.shared_data.tracker_image_hosts == {
        TrackerSelection.AITHER: ImageUploadFromTo(
            ImageSource.IMAGES, ImageHost.DISABLED
        )
    }


def test_sync_tracker_image_hosts_skips_a_row_missing_its_combo_data(
    qapp: Any, sample_media: Path
) -> None:
    """Direct regression test for the crash itself, independent of Qt's
    signal-emission timing. PySide reports an exception raised inside a slot
    invoked through real signal emission via its own exception hook rather
    than letting it propagate as a normal Python exception (this is exactly
    the "Unhandled exception: ... Traceback" console dump the crash was
    originally reported as), so a test that only reproduces the timing can
    pass even when the underlying bug is still present. This test instead
    hands `_sync_tracker_image_hosts` the exact malformed row shape it saw
    mid-construction directly: a row whose image-host column is still plain
    (empty) header text because no combo box has been registered for it in
    `combo_box_map` yet."""
    context = ProcessingContext()
    _populate(context, sample_media)
    page = _fake_page(context)
    page.tracker_process_tree.add_row(headers=("Aither", "", "⌛ Queued"))

    page._sync_tracker_image_hosts()  # must not raise

    assert context.shared_data.tracker_image_hosts == {}


def test_gathered_tracker_data_comes_from_the_payload(
    qapp: Any, sample_media: Path
) -> None:
    context = ProcessingContext()
    _populate(context, sample_media)
    page = _fake_page(context)
    ProcessPage.add_tracker_items(page)

    tracker_data = ProcessPage._gather_tracker_data(page, sample_media)

    assert tracker_data is not None
    assert list(tracker_data) == ["Aither"]
    entry = tracker_data["Aither"]
    assert entry["image_host_data"] == ImageUploadFromTo(
        ImageSource.IMAGES, ImageHost.CHEVERETO_V3
    )
    assert entry["path"].name == f"{sample_media.stem}.torrent"


def test_a_selection_change_reaches_the_payload(qapp: Any, sample_media: Path) -> None:
    context = ProcessingContext()
    _populate(context, sample_media)
    page = _fake_page(context)
    ProcessPage.add_tracker_items(page)
    combo = next(iter(page.tracker_process_tree.combo_box_map.values()))

    combo.setCurrentIndex(
        combo.findText(
            ProcessPage._image_host_label(ImageSource.IMAGES, ImageHost.PIXHOST)
        )
    )
    page._sync_tracker_image_hosts()

    assert (
        context.shared_data.tracker_image_hosts[TrackerSelection.AITHER].img_to
        is ImageHost.PIXHOST
    )


# --------------------------------------------------------------------------
# deferring the trackers a run could not upload
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "outcome",
    [
        TrackerRunOutcome.NOT_ATTEMPTED,
        TrackerRunOutcome.SKIPPED,
        TrackerRunOutcome.UPLOAD_FAILED,
    ],
)
def test_outcomes_that_never_reached_the_tracker_may_be_deferred(
    outcome: TrackerRunOutcome,
) -> None:
    assert outcome.is_safe_to_reupload()


@pytest.mark.parametrize(
    "outcome",
    [
        TrackerRunOutcome.UPLOADED,
        TrackerRunOutcome.MAY_HAVE_UPLOADED,
        TrackerRunOutcome.INJECTION_FAILED,
        TrackerRunOutcome.UPLOAD_DISABLED,
    ],
)
def test_outcomes_that_may_have_landed_are_never_deferred(
    outcome: TrackerRunOutcome,
) -> None:
    """The duplicate-upload guard.

    Tested directly on the predicate rather than through signal emission,
    because PySide routes an exception raised inside a signal-invoked slot
    through its own hook instead of letting pytest see it -- a timing-based
    test here can pass while the guard is broken.
    """
    assert not outcome.is_safe_to_reupload()


def test_deferrable_trackers_keeps_only_the_safe_ones() -> None:
    page = SimpleNamespace(
        _run_outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOAD_FAILED,
            TrackerSelection.LST: TrackerRunOutcome.MAY_HAVE_UPLOADED,
            TrackerSelection.BEYOND_HD: TrackerRunOutcome.NOT_ATTEMPTED,
            TrackerSelection.HDB: TrackerRunOutcome.INJECTION_FAILED,
        }
    )

    deferrable = ProcessPage._deferrable_trackers(page)

    assert set(deferrable) == {TrackerSelection.HUNO, TrackerSelection.BEYOND_HD}


def test_nothing_is_offered_when_every_tracker_uploaded() -> None:
    page = SimpleNamespace(
        _run_outcomes={TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED},
        _deferrable_trackers=lambda: {},
    )

    # must return without prompting at all
    ProcessPage._offer_deferred_job(page)


def test_declining_the_offer_saves_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[object] = []
    page = SimpleNamespace(
        _run_outcomes={TrackerSelection.HUNO: TrackerRunOutcome.UPLOAD_FAILED},
        _deferrable_trackers=lambda: {
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOAD_FAILED
        },
        _save_job=lambda **kwargs: saved.append(kwargs),
        _OUTCOME_LABELS=ProcessPage._OUTCOME_LABELS,
    )
    monkeypatch.setattr(
        process_module.QMessageBox,
        "question",
        lambda *_a, **_k: process_module.QMessageBox.StandardButton.No,
    )

    ProcessPage._offer_deferred_job(page)

    assert saved == []


def test_accepting_the_offer_saves_only_the_deferrable_trackers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[dict] = []
    page = SimpleNamespace(
        _run_outcomes={},
        _deferrable_trackers=lambda: {
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOAD_FAILED,
            TrackerSelection.BEYOND_HD: TrackerRunOutcome.NOT_ATTEMPTED,
        },
        _save_job=lambda **kwargs: saved.append(kwargs),
        _OUTCOME_LABELS=ProcessPage._OUTCOME_LABELS,
    )
    monkeypatch.setattr(
        process_module.QMessageBox,
        "question",
        lambda *_a, **_k: process_module.QMessageBox.StandardButton.Yes,
    )

    ProcessPage._offer_deferred_job(page)

    assert saved == [
        {"keep_trackers": {TrackerSelection.HUNO, TrackerSelection.BEYOND_HD}}
    ]


def test_a_deferred_job_only_stores_nfos_for_the_trackers_it_keeps(
    qapp: Any, sample_media: Path, tmp_path: Path
) -> None:
    """A dropped tracker's NFO left in the folder implies the job still covers it."""
    context = ProcessingContext()
    _populate(context, sample_media)
    context.shared_data.tracker_image_hosts[TrackerSelection.HUNO] = ImageUploadFromTo(
        ImageSource.IMAGES, ImageHost.CHEVERETO_V3
    )
    context.shared_data.tracker_release_data = {
        TrackerSelection.AITHER: {"title": "a", "nfo": "already uploaded"},
        TrackerSelection.HUNO: {"title": "h", "nfo": "still to go"},
    }

    page = SimpleNamespace(context=context)
    page._first_generated_torrent = lambda: None
    directory = tmp_path / "job"
    directory.mkdir()

    document = ProcessPage._build_job_document(page, directory, {TrackerSelection.HUNO})

    assert set(document["shared_data"]["tracker_release_data"]) == {"HUNO"}
    assert {path.name for path in (directory / "nfo").iterdir()} == {"huno.txt"}


# --------------------------------------------------------------------------
# load dialog
# --------------------------------------------------------------------------
def test_load_dialog_lists_saved_jobs_and_reports_the_choice(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    job = store.build_job(
        name="My job",
        summary=JobSummary(title="Example", year=2024, trackers=["Aither"]),
        context={},
        config_profile="config",
    )
    store.save_job(job, working_dir)

    dialog = LoadJobDialog("config")
    try:
        assert dialog.job_tree.topLevelItemCount() == 1
        item = dialog.job_tree.topLevelItem(0)
        assert item is not None
        assert item.text(0) == "My job"
        assert item.text(1) == "Example (2024)"
        assert item.text(4) == "config"
        dialog._accept_selection()
        assert dialog.selected_listing is not None
        assert dialog.selected_listing.job_id == job.job_id
        assert dialog.switch_profile_requested is False
        assert dialog.result() == QDialog.DialogCode.Accepted
    finally:
        dialog.deleteLater()


def test_load_dialog_is_empty_and_inert_without_jobs(
    qapp: Any, patched_working_dirs: None
) -> None:
    dialog = LoadJobDialog("config")
    try:
        assert dialog.job_tree.topLevelItemCount() == 0
        dialog._accept_selection()
        assert dialog.selected_listing is None
    finally:
        dialog.deleteLater()


def test_a_job_from_another_config_is_listed_but_not_directly_loadable(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Resuming under the wrong config would upload with the wrong settings."""
    store.save_job(
        store.build_job("Other", JobSummary(), {}, config_profile="anime"), working_dir
    )

    dialog = LoadJobDialog("config")
    try:
        assert dialog.job_tree.topLevelItemCount() == 1
        dialog._accept_selection()
        assert dialog.selected_listing is None

        dialog._accept_with_switch()
        assert dialog.selected_listing is not None
        assert dialog.selected_listing.config_profile == "anime"
        assert dialog.switch_profile_requested is True
    finally:
        dialog.deleteLater()


def test_a_job_without_a_recorded_config_stays_loadable(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """Jobs predating config pairing must not be locked out of every profile."""
    store.save_job(
        store.build_job("Legacy", JobSummary(), {}, config_profile=""), working_dir
    )

    dialog = LoadJobDialog("config")
    try:
        dialog._accept_selection()
        assert dialog.selected_listing is not None
        assert dialog.switch_profile_requested is False
    finally:
        dialog.deleteLater()


def _save_listing(
    working_dir: Path, name: str, *, prepared: bool, profile: str = "config"
) -> None:
    """Write a job whose document is or isn't prepared, for picker tests."""
    context = (
        {"shared_data": {"tracker_release_data": {"AITHER": {"title": "x"}}}}
        if prepared
        else {"shared_data": {}}
    )
    store.save_job(
        store.build_job(name, JobSummary(), context, config_profile=profile),
        working_dir,
    )


def test_only_prepared_jobs_on_this_config_can_be_queued(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    """A queue has nobody to answer a prompt, and no business using another
    config's credentials."""
    _save_listing(working_dir, "ready", prepared=True)
    _save_listing(working_dir, "raw", prepared=False)
    _save_listing(working_dir, "other-config", prepared=True, profile="anime")

    dialog = LoadJobDialog("config")
    try:
        dialog.job_tree.selectAll()
        queueable = [listing.name for listing in dialog.queueable_listings()]
        assert queueable == ["ready"]
        # a mixed selection must not silently drop what it cannot run
        assert not dialog.queue_btn.isEnabled()
    finally:
        dialog.deleteLater()


def test_selecting_only_prepared_jobs_enables_the_queue(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save_listing(working_dir, "ready-one", prepared=True)
    _save_listing(working_dir, "ready-two", prepared=True)

    dialog = LoadJobDialog("config")
    try:
        dialog.job_tree.selectAll()
        assert dialog.queue_btn.isEnabled()

        dialog._accept_queue()
        assert {listing.name for listing in dialog.queued_listings} == {
            "ready-one",
            "ready-two",
        }
        assert dialog.selected_listing is None
    finally:
        dialog.deleteLater()


def test_the_picker_shows_whether_a_job_is_prepared(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save_listing(working_dir, "ready", prepared=True)

    dialog = LoadJobDialog("config")
    try:
        item = dialog.job_tree.topLevelItem(0)
        assert item is not None
        assert item.text(5) == "Prepared"
    finally:
        dialog.deleteLater()


def test_load_dialog_deletes_the_selected_job(
    qapp: Any,
    working_dir: Path,
    patched_working_dirs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store.save_job(
        store.build_job("Doomed", JobSummary(), {}, config_profile="config"),
        working_dir,
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
    )

    dialog = LoadJobDialog("config")
    try:
        dialog._delete_selected()
        assert dialog.job_tree.topLevelItemCount() == 0
        assert store.list_jobs([working_dir]) == []
    finally:
        dialog.deleteLater()


def test_resume_target_is_the_final_page_so_the_flow_terminates() -> None:
    assert WizardPages.PROCESS_PAGE.value == max(page.value for page in WizardPages)


# --------------------------------------------------------------------------
# wizard jump + load-time validation
# --------------------------------------------------------------------------
def test_start_id_plus_restart_jumps_straight_to_the_process_page(qapp: Any) -> None:
    """QWizard has no setCurrentId; resuming relies on setStartId + restart().

    Also guards the reason that combination was chosen over walking the flow:
    the skipped pages must not be left in the history for Back to reach.
    """
    wizard = QWizard()
    for page_id in (
        WizardPages.INPUT_PAGE.value,
        WizardPages.TRACKERS_PAGE.value,
        WizardPages.PROCESS_PAGE.value,
    ):
        wizard.setPage(page_id, QWizardPage())

    wizard.setStartId(WizardPages.PROCESS_PAGE.value)
    wizard.restart()

    assert wizard.currentId() == WizardPages.PROCESS_PAGE.value
    assert wizard.visitedIds() == [WizardPages.PROCESS_PAGE.value]

    # and a subsequent start-over restores the real entry point
    wizard.setStartId(WizardPages.INPUT_PAGE.value)
    wizard.restart()
    assert wizard.currentId() == WizardPages.INPUT_PAGE.value


def test_help_button_slot_can_carry_the_load_job_button(qapp: Any) -> None:
    """All three CustomButton slots are taken, so Load Job rides on HelpButton.

    Guards that a custom button placed in that slot really is shown when the
    layout asks for it, and hidden when a layout omits it.
    """
    wizard = QWizard()
    wizard.setPage(WizardPages.INPUT_PAGE.value, QWizardPage())
    load_button = QPushButton("Load Job", wizard)
    wizard.setButton(QWizard.WizardButton.HelpButton, load_button)
    wizard.setOption(QWizard.WizardOption.HaveHelpButton)
    wizard.setButtonLayout(
        (
            QWizard.WizardButton.HelpButton,
            QWizard.WizardButton.Stretch,
            QWizard.WizardButton.CommitButton,
        )
    )
    wizard.show()
    try:
        assert wizard.button(QWizard.WizardButton.HelpButton) is load_button
        assert load_button.isVisible()

        wizard.setButtonLayout(
            (QWizard.WizardButton.Stretch, QWizard.WizardButton.CommitButton)
        )
        assert not load_button.isVisible()
    finally:
        wizard.close()
        wizard.deleteLater()


def test_a_job_whose_media_vanished_is_refused(
    qapp: Any, sample_media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = ProcessingContext()
    _populate(context, sample_media)
    sample_media.unlink()
    monkeypatch.setattr(QMessageBox, "critical", lambda *_a, **_k: None)

    assert (
        MainWindowWizard._restored_job_is_usable(_wizard_stub(), "Example", context)
        is False
    )


def test_missing_screenshots_are_surfaced_but_the_user_may_continue(
    qapp: Any, sample_media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = ProcessingContext()
    _populate(context, sample_media)  # loaded_images points at a file never created
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
    )

    assert MainWindowWizard._restored_job_is_usable(_wizard_stub(), "Example", context)

    monkeypatch.setattr(
        QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.No
    )
    assert not MainWindowWizard._restored_job_is_usable(
        _wizard_stub(), "Example", context
    )


def test_intact_job_passes_validation(qapp: Any, sample_media: Path) -> None:
    context = ProcessingContext()
    _populate(context, sample_media)
    image = sample_media.parent / "img1.png"
    image.write_bytes(b"not really a png, but it exists")

    assert MainWindowWizard._restored_job_is_usable(_wizard_stub(), "Example", context)


# --------------------------------------------------------------------------
# the active config has to be able to actually serve the job
# --------------------------------------------------------------------------
def test_a_tracker_disabled_in_the_active_config_is_flagged(
    qapp: Any, sample_media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise this only surfaces as a no-op partway through the upload."""
    context = ProcessingContext()
    _populate(context, sample_media)
    asked: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _self, _title, text, *_a, **_k: (
            asked.append(text),
            QMessageBox.StandardButton.No,
        )[1],
    )

    allowed = MainWindowWizard._confirm_profile_can_serve_job(
        _wizard_stub(upload_enabled=False), "Example", context
    )

    assert allowed is False
    assert "uploads are disabled" in asked[0]


def test_a_missing_nfo_template_is_flagged(
    qapp: Any, sample_media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = ProcessingContext()
    _populate(context, sample_media)
    asked: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _self, _title, text, *_a, **_k: (
            asked.append(text),
            QMessageBox.StandardButton.Yes,
        )[1],
    )

    allowed = MainWindowWizard._confirm_profile_can_serve_job(
        _wizard_stub(nfo_template="a-template-that-does-not-exist"), "Example", context
    )

    assert allowed is True
    assert "no longer exists" in asked[0]
    # templates are global, so profile pairing cannot pin their content --
    # the warning has to say so
    assert "shared across all configs" in asked[0]


def test_a_tracker_absent_from_the_active_config_is_flagged(
    qapp: Any, sample_media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = ProcessingContext()
    _populate(context, sample_media)
    asked: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _self, _title, text, *_a, **_k: (
            asked.append(text),
            QMessageBox.StandardButton.No,
        )[1],
    )

    stub = _wizard_stub()
    stub.config.settings.trackers.by_selection = dict  # no trackers configured

    assert (
        MainWindowWizard._confirm_profile_can_serve_job(stub, "Example", context)
        is False
    )
    assert "not configured" in asked[0]


def test_a_template_edited_since_preparing_is_flagged(
    qapp: Any, sample_media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Frozen NFOs win, so the change must at least be said out loud."""
    context = ProcessingContext()
    _populate(context, sample_media)
    context.shared_data.template_fingerprints["default"] = "a-stale-digest"
    selector = SimpleNamespace(read_template=lambda **_k: "the template changed")

    warnings = MainWindowWizard._stale_template_warnings(context, cast(Any, selector))

    assert len(warnings) == 1
    assert "default" in warnings[0]
    assert "saved NFO will be uploaded" in warnings[0]


def test_an_unchanged_template_is_not_flagged(qapp: Any, sample_media: Path) -> None:
    context = ProcessingContext()
    _populate(context, sample_media)
    body = "the template body"
    context.shared_data.template_fingerprints["default"] = template_fingerprint(body)
    selector = SimpleNamespace(read_template=lambda **_k: body)

    assert MainWindowWizard._stale_template_warnings(context, cast(Any, selector)) == []


def test_a_job_with_no_frozen_templates_is_not_flagged(
    qapp: Any, sample_media: Path
) -> None:
    """An unprepared job froze nothing, so there is nothing to go stale."""
    context = ProcessingContext()
    _populate(context, sample_media)
    selector = SimpleNamespace(read_template=lambda **_k: "anything")

    assert MainWindowWizard._stale_template_warnings(context, cast(Any, selector)) == []


def test_a_fully_served_job_asks_nothing(qapp: Any, sample_media: Path) -> None:
    context = ProcessingContext()
    _populate(context, sample_media)

    # no QMessageBox patch: a prompt here would fail the test by blocking
    assert MainWindowWizard._confirm_profile_can_serve_job(
        _wizard_stub(), "Example", context
    )
