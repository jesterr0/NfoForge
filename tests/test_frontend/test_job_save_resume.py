"""Coverage for saving a job and resuming it at the process page."""

from pathlib import Path
import struct
from types import SimpleNamespace
from typing import Any, cast
import wave

from pymediainfo import MediaInfo
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QWizard,
    QWizardPage,
)
import pytest
from torf import Torrent

from src.backend.jobs import (
    MediaFingerprint,
    context_from_dict,
    context_to_dict,
    fingerprint_files,
    store,
    template_fingerprint,
    torrent_content_files,
)
from src.backend.jobs.models import JobSummary
from src.backend.upload_retry import TrackerRunOutcome
from src.backend.utils.media_info_utils import clear_full_mi_str_cache
from src.context.processing_context import ProcessingContext
from src.enums.image_host import ImageHost, ImageSource
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.upload_process import UploadProcessMode
from src.enums.wizard import WizardPages
from src.frontend.custom_widgets import load_job_dialog as load_job_dialog_module
from src.frontend.custom_widgets.combo_qtree import ComboBoxTreeWidget
from src.frontend.custom_widgets.load_job_dialog import LoadJobDialog
from src.frontend.global_signals import GSigs
from src.frontend.wizards import process as process_module, wizard as wizard_module
from src.frontend.wizards.process import ProcessPage
from src.frontend.wizards.wizard import MainWindowWizard
from src.packages.custom_types import ImageUploadData, ImageUploadFromTo
from src.payloads.image_hosts import ImagePayloadBase


@pytest.fixture(autouse=True)
def _clear_mi_cache() -> None:
    # a test that seeds this module-global cache and then fails its own
    # assertion would otherwise leave the entry behind for the rest of the
    # session, so clearing it up front rather than trusting the code under
    # test to do so is what keeps tests independent
    clear_full_mi_str_cache()


@pytest.fixture
def working_dir(tmp_path: Path) -> Path:
    return tmp_path / "nfoforge"


@pytest.fixture
def patched_working_dirs(working_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the picker's profile scan at the test's working directory."""
    monkeypatch.setattr(
        load_job_dialog_module, "unique_working_dirs", lambda: [working_dir]
    )


def _open_dialog(qapp: Any, active_profile: str | None) -> LoadJobDialog:
    """Construct the picker and wait for its background listing load to land.

    Listing runs on a `_ListingLoader` thread now, so the tree below is empty
    until that thread's `loaded` signal is delivered -- every test here is
    about what the picker does with a loaded list, not about the loading
    itself (that is covered in `test_load_job_dialog.py`), so waiting once
    here is the fix.
    """
    dialog = LoadJobDialog(active_profile)
    assert dialog._loader is not None
    dialog._loader.wait(5000)
    qapp.processEvents()
    return dialog


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
    media_input.file_list_mediainfo[media] = MediaInfo.parse(  # pyright: ignore[reportArgumentType]
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
            wizard,  # pyright: ignore[reportArgumentType]
            job_name,
            context,  # pyright: ignore[reportArgumentType]
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
    page.image_host_banner = QLabel()
    page._apply_remembered_image_host = lambda combo, tracker, upload_type, restored: (
        ProcessPage._apply_remembered_image_host(  # pyright: ignore[reportArgumentType]
            page, combo, tracker, upload_type, restored
        )
    )
    page._show_image_host_notice = lambda notes: ProcessPage._show_image_host_notice(  # pyright: ignore[reportArgumentType]
        page, notes
    )
    page._sync_tracker_image_hosts = lambda: ProcessPage._sync_tracker_image_hosts(page)  # pyright: ignore[reportArgumentType]
    page._tree_combo_changed = lambda combo, idx: ProcessPage._tree_combo_changed(
        page,  # pyright: ignore[reportArgumentType]
        combo,
        idx,
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
    assert restored.media_input.require_mediainfo(sample_media).tracks  # pyright: ignore[reportAttributeAccessIssue]


def test_completed_upload_is_kept_as_a_source_less_archive(
    sample_media: Path, working_dir: Path
) -> None:
    context = ProcessingContext()
    _populate(context, sample_media)
    context.shared_data.tracker_release_data = {
        TrackerSelection.AITHER: {"title": "Example", "nfo": "release nfo"}
    }
    image = context.shared_data.loaded_images[0]
    image.write_bytes(b"screenshot")
    context.media_input.require_working_dir().mkdir()
    base = context.media_input.require_working_dir() / "Example.Movie.2024.base.torrent"
    torrent = Torrent(path=sample_media, private=True)
    torrent.generate()
    torrent.write(base)

    page = SimpleNamespace(
        context=context,
        config=SimpleNamespace(
            settings=SimpleNamespace(general=SimpleNamespace(working_dir=working_dir)),
            program=SimpleNamespace(current_config="config"),
        ),
        _run_phase=process_module.RunPhase.FULL,
        _run_outcomes={TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED},
        _on_text_update=lambda _text: None,
    )
    page._default_job_name = lambda: ProcessPage._default_job_name(page)
    page._first_generated_torrent = lambda: base
    page._build_job_document = lambda directory, keep: ProcessPage._build_job_document(
        page, directory, keep
    )
    page._job_summary = lambda keep=None: ProcessPage._job_summary(page, keep)

    assert ProcessPage._archive_completed_run(page)  # pyright: ignore[reportArgumentType]
    listings = store.list_jobs([working_dir])
    assert len(listings) == 1
    assert listings[0].archived
    assert listings[0].source_less_ready
    saved = store.load_job(listings[0].path)
    assert saved.uploaded_trackers == [TrackerSelection.AITHER.name]

    sample_media.unlink()

    assert store.list_jobs([working_dir])[0].source_less_ready


def test_adding_trackers_keeps_one_left_pending_by_an_earlier_run(
    sample_media: Path, working_dir: Path
) -> None:
    """Adding a tracker must not discard what an earlier run left unfinished.

    `_run_outcomes` only covers the trackers of the run that just ended, so
    narrowing the archive to it drops a tracker that failed last time -- its
    prepared title and NFO go with it, and the sidecars are pruned. The user
    would have no way back except preparing that tracker over again, and no
    indication it happened.
    """
    context = ProcessingContext()
    _populate(context, sample_media)
    context.shared_data.tracker_release_data = {
        TrackerSelection.AITHER: {"title": "Example", "nfo": "aither nfo"},
        TrackerSelection.HUNO: {"title": "Example", "nfo": "huno nfo"},
    }
    context.shared_data.loaded_images[0].write_bytes(b"screenshot")
    context.media_input.require_working_dir().mkdir()
    base = context.media_input.require_working_dir() / "Example.Movie.2024.base.torrent"
    torrent = Torrent(path=sample_media, private=True)
    torrent.generate()
    torrent.write(base)

    page = SimpleNamespace(
        context=context,
        config=SimpleNamespace(
            settings=SimpleNamespace(general=SimpleNamespace(working_dir=working_dir)),
            program=SimpleNamespace(current_config="config"),
        ),
        _run_phase=process_module.RunPhase.FULL,
        _run_outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOAD_FAILED,
        },
        _on_text_update=lambda _text: None,
    )
    page._default_job_name = lambda: ProcessPage._default_job_name(page)
    page._first_generated_torrent = lambda: base
    page._build_job_document = lambda directory, keep: ProcessPage._build_job_document(
        page, directory, keep
    )
    page._job_summary = lambda keep=None: ProcessPage._job_summary(page, keep)

    assert ProcessPage._archive_completed_run(page)  # pyright: ignore[reportArgumentType]
    path = store.list_jobs([working_dir])[0].path
    assert store.load_job(path).summary.trackers == [str(TrackerSelection.HUNO)]

    # Now add LST to that archive. Resuming clears the image-host map and
    # re-fills it with only the additions, exactly as `_load_job` does, so HUNO
    # has no row in this run at all.
    context.loaded_job_path = path
    context.loaded_job_archived = True
    context.loaded_uploaded_trackers = {TrackerSelection.AITHER}
    context.shared_data.tracker_release_data[TrackerSelection.LST] = {
        "title": "Example",
        "nfo": "lst nfo",
    }
    context.shared_data.tracker_image_hosts.clear()
    context.shared_data.tracker_image_hosts[TrackerSelection.LST] = ImageUploadFromTo(
        ImageSource.IMAGES, ImageHost.CHEVERETO_V3
    )
    page._run_outcomes = {TrackerSelection.LST: TrackerRunOutcome.UPLOADED}

    assert ProcessPage._archive_completed_run(page)  # pyright: ignore[reportArgumentType]

    saved = store.load_job(path)
    assert set(saved.uploaded_trackers) == {
        TrackerSelection.AITHER.name,
        TrackerSelection.LST.name,
    }
    # HUNO was neither uploaded nor part of this run: it stays pending, keeps
    # its frozen NFO, and remains visible to the picker.
    assert saved.summary.trackers == [str(TrackerSelection.HUNO)]
    shared = saved.context["shared_data"]
    assert TrackerSelection.HUNO.name in shared["tracker_release_data"]
    assert (Path(path) / store.JOB_NFO_DIR_NAME / "huno.txt").is_file()
    # ...and it has to be runnable, not merely present. The summary saying the
    # job still covers HUNO while `selected_trackers` omits it is a job the
    # picker offers and the wizard then builds no tracker row for -- the
    # prepared NFO survives on disk and is never reachable again.
    assert shared["selected_trackers"] == [TrackerSelection.HUNO.name]


def test_an_uncertain_tracker_keeps_everything_but_the_ability_to_run(
    sample_media: Path, working_dir: Path
) -> None:
    """An upload nobody could confirm must stay resolvable.

    Narrowing it out of the archive left only its name in
    `uncertain_trackers`, so the picker went on offering "No, safe to upload"
    for a tracker whose title, NFO sidecar and image host had already been
    deleted -- a resolution the data could no longer support.
    """
    context = ProcessingContext()
    _populate(context, sample_media)
    context.shared_data.selected_trackers = [
        TrackerSelection.AITHER,
        TrackerSelection.HUNO,
    ]
    context.shared_data.tracker_image_hosts[TrackerSelection.HUNO] = ImageUploadFromTo(
        ImageSource.IMAGES, ImageHost.PIXHOST
    )
    context.shared_data.tracker_release_data = {
        TrackerSelection.AITHER: {"title": "Example", "nfo": "aither nfo"},
        TrackerSelection.HUNO: {"title": "Example", "nfo": "huno nfo"},
    }
    context.shared_data.loaded_images[0].write_bytes(b"screenshot")
    context.media_input.require_working_dir().mkdir()

    page = SimpleNamespace(
        context=context,
        config=SimpleNamespace(
            settings=SimpleNamespace(general=SimpleNamespace(working_dir=working_dir)),
            program=SimpleNamespace(current_config="config"),
        ),
        _run_phase=process_module.RunPhase.FULL,
        _run_outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED,
            TrackerSelection.HUNO: TrackerRunOutcome.MAY_HAVE_UPLOADED,
        },
        _on_text_update=lambda _text: None,
    )
    page._default_job_name = lambda: ProcessPage._default_job_name(page)
    page._first_generated_torrent = lambda: None
    page._build_job_document = lambda directory, keep: ProcessPage._build_job_document(
        page, directory, keep
    )
    page._job_summary = lambda keep=None: ProcessPage._job_summary(page, keep)

    assert ProcessPage._archive_completed_run(page)  # pyright: ignore[reportArgumentType]

    path = store.list_jobs([working_dir])[0].path
    saved = store.load_job(path)
    shared = saved.context["shared_data"]
    assert saved.uncertain_trackers == [TrackerSelection.HUNO.name]
    # cannot upload again...
    assert shared["selected_trackers"] == []
    # ...but everything a resolution needs is still here
    assert shared["tracker_release_data"][TrackerSelection.HUNO.name]["title"] == (
        "Example"
    )
    assert TrackerSelection.HUNO.name in shared["tracker_image_hosts"]
    assert (Path(path) / store.JOB_NFO_DIR_NAME / "huno.txt").is_file()


def test_a_fully_uploaded_archive_still_carries_its_image_urls(
    sample_media: Path, working_dir: Path
) -> None:
    """URLs are the host's, not the tracker's, so narrowing must not take them.

    Every per-tracker map goes when nothing is left pending, which left the
    archive of a completely successful run holding no image URLs at all -- so
    a tracker added to it later re-uploaded the same screenshots, or had
    nothing to upload once `images/` was gone.
    """
    context = ProcessingContext()
    _populate(context, sample_media)
    context.shared_data.tracker_release_data = {
        TrackerSelection.AITHER: {"title": "Example", "nfo": "aither nfo"}
    }
    context.shared_data.loaded_images[0].write_bytes(b"screenshot")
    context.media_input.require_working_dir().mkdir()
    uploaded = {0: ImageUploadData(url="https://pixhost/0.png", medium_url=None)}
    context.shared_data.uploaded_images[TrackerSelection.AITHER] = dict(uploaded)
    context.shared_data.uploaded_image_hosts[TrackerSelection.AITHER] = (
        ImageHost.PIXHOST
    )
    context.shared_data.uploaded_images_by_host[ImageHost.PIXHOST] = dict(uploaded)

    page = SimpleNamespace(
        context=context,
        config=SimpleNamespace(
            settings=SimpleNamespace(general=SimpleNamespace(working_dir=working_dir)),
            program=SimpleNamespace(current_config="config"),
        ),
        _run_phase=process_module.RunPhase.FULL,
        _run_outcomes={TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED},
        _on_text_update=lambda _text: None,
    )
    page._default_job_name = lambda: ProcessPage._default_job_name(page)
    page._first_generated_torrent = lambda: None
    page._build_job_document = lambda directory, keep: ProcessPage._build_job_document(
        page, directory, keep
    )
    page._job_summary = lambda keep=None: ProcessPage._job_summary(page, keep)

    assert ProcessPage._archive_completed_run(page)  # pyright: ignore[reportArgumentType]

    saved = store.load_job(store.list_jobs([working_dir])[0].path)
    shared = saved.context["shared_data"]
    assert shared["uploaded_images"] == {}
    assert shared["uploaded_images_by_host"] == [
        {
            "name": "PIXHOST",
            "type": "ImageHost",
            "images": {"0": {"url": "https://pixhost/0.png", "medium_url": None}},
        }
    ]


def test_content_size_is_recorded_even_without_a_base_torrent(
    sample_media: Path, working_dir: Path
) -> None:
    """Two trackers size a disc release off the filesystem when it is absent.

    `beyondhd` and `passthepopcorn` both fall back to
    `input_path.stat().st_size`, which a source-less run cannot do -- and save
    time is the last moment the media is guaranteed to be there to measure.
    """
    context = ProcessingContext()
    _populate(context, sample_media)
    context.shared_data.loaded_images[0].write_bytes(b"screenshot")
    directory = working_dir / "jobs" / "abc"
    directory.mkdir(parents=True)

    page = SimpleNamespace(context=context)
    page._first_generated_torrent = lambda: None

    document = ProcessPage._build_job_document(page, directory, None)  # pyright: ignore[reportArgumentType]

    assert "base_torrent" not in document
    assert document["media_input"]["content_size"] == sample_media.stat().st_size


def test_a_prepared_plain_job_is_not_silently_overwritten(
    sample_media: Path, working_dir: Path
) -> None:
    """Only an archive is updated in place.

    Preparing an ordinary saved job keeps the named save it always had -- the
    in-place path exists for archives, which may have no source left to capture
    MediaInfo from.
    """
    context = ProcessingContext()
    _populate(context, sample_media)
    context.loaded_job_path = working_dir / "some-job"
    context.loaded_job_archived = False
    page = SimpleNamespace(context=context)

    assert ProcessPage._save_prepared_archive(page) is False  # pyright: ignore[reportArgumentType]


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


def test_a_source_less_archive_offers_the_hosts_it_already_uploaded_to(
    qapp: Any, sample_media: Path
) -> None:
    """With no local screenshots left, the stored URLs are the only option.

    The combo only offered real hosts when there were `loaded_images` or
    `url_data`, so an archive whose `images/` had gone showed nothing but
    `Disabled` -- and silently uploaded to nobody. Nothing is sent for a host
    the job already holds URLs for, so neither the files nor the host's own
    credentials are needed to offer it.
    """
    context = ProcessingContext()
    _populate(context, sample_media)
    context.shared_data.loaded_images = None
    context.shared_data.generated_images = False
    context.shared_data.url_data.clear()
    context.shared_data.tracker_image_hosts.clear()
    context.shared_data.uploaded_images_by_host[ImageHost.PIXHOST] = {
        0: ImageUploadData(url="https://pixhost/0.png", medium_url=None)
    }
    page = _fake_page(context)

    ProcessPage.add_tracker_items(page)

    combo = page.tracker_process_tree.combo_box_map[
        (page.tracker_process_tree.topLevelItem(0), 1)
    ]
    offered = {combo.itemText(index) for index in range(combo.count())}
    assert any("Pixhost" in text for text in offered)
    # a host the bundle cannot serve must not be offered as if it could
    assert not any("Chevereto" in text for text in offered)


def test_a_saved_host_that_is_gone_is_named_instead_of_silently_dropped(
    qapp: Any, sample_media: Path
) -> None:
    """Settings -> Image Hosts is read live, so a job's host can vanish.

    The row then took whatever was first -- `Disabled` -- and a run that was
    meant to carry screenshots uploaded none, looking exactly like a row the
    user had turned off on purpose.
    """
    context = ProcessingContext()
    _populate(context, sample_media)  # saved against Chevereto v3
    page = _fake_page(context)
    # the host the job chose is no longer offered by this config
    page.config.settings.image_hosts.by_selection = lambda: {}

    ProcessPage.add_tracker_items(page)

    assert (
        context.shared_data.tracker_image_hosts[TrackerSelection.AITHER].img_to
        is ImageHost.DISABLED
    )
    assert not page.image_host_banner.isHidden()
    notice = page.image_host_banner.text()
    assert "Chevereto v3" in notice
    assert "Aither" in notice
    assert "Disabled" in notice


def test_a_saved_host_replaced_by_the_global_preference_is_named_too(
    qapp: Any, sample_media: Path
) -> None:
    """Landing on a *different* host is the worse of the two substitutions.

    The screenshots go somewhere the job never chose, which also makes the
    URLs it already holds for its own host unusable.
    """
    context = ProcessingContext()
    _populate(context, sample_media)  # saved against Chevereto v3
    page = _fake_page(context, last_used={TrackerSelection.AITHER: ImageHost.PIXHOST})
    page.config.settings.image_hosts.by_selection = lambda: {
        ImageHost.PIXHOST: ImagePayloadBase(base_url="https://pix.test", enabled=True)
    }

    ProcessPage.add_tracker_items(page)

    assert (
        context.shared_data.tracker_image_hosts[TrackerSelection.AITHER].img_to
        is ImageHost.PIXHOST
    )
    notice = page.image_host_banner.text()
    assert "Chevereto v3" in notice
    assert "Pixhost" in notice


def test_a_host_that_is_still_offered_says_nothing(
    qapp: Any, sample_media: Path
) -> None:
    context = ProcessingContext()
    _populate(context, sample_media)
    page = _fake_page(context)

    ProcessPage.add_tracker_items(page)

    assert page.image_host_banner.text() == ""
    assert page.image_host_banner.isHidden()


def test_a_fresh_run_with_no_remembered_host_says_nothing(
    qapp: Any, sample_media: Path
) -> None:
    """`Disabled` is only worth reporting when it displaced something."""
    context = ProcessingContext()
    _populate(context, sample_media)
    context.shared_data.tracker_image_hosts.clear()
    page = _fake_page(context)

    ProcessPage.add_tracker_items(page)

    assert page.image_host_banner.text() == ""
    assert page.image_host_banner.isHidden()


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


def test_a_run_with_no_trackers_clears_the_hosts_it_restored(
    qapp: Any, sample_media: Path
) -> None:
    """The rows are the run, so no rows has to mean no trackers.

    A restored job can arrive holding an image host for a tracker it is not
    going to run -- an unconfirmed upload keeps its entry. The sync only ran
    when there was something to build a row for, so those entries survived a
    run that showed none, and `_gather_tracker_data` handed the backend a
    tracker the user never saw listed.
    """
    context = ProcessingContext()
    _populate(context, sample_media)
    context.shared_data.selected_trackers = []
    page = _fake_page(context)

    ProcessPage.add_tracker_items(page)

    assert page.tracker_process_tree.topLevelItemCount() == 0
    assert context.shared_data.tracker_image_hosts == {}


def test_only_the_live_process_page_answers_the_process_button(
    qapp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Process button is the wizard's, so every page ever built hears it.

    Rebuilding the wizard -- Start Over, or resuming a job -- removes the old
    page and schedules its deletion, but the subscription outlives the removal
    until that delete actually runs, which nothing waits for. Two pages
    answering one press is two runs from two different contexts: the live one,
    and a stale one uploading to whatever trackers its own context still
    names. A page built by Start Over has an empty context, so its run reports
    having no trackers at all -- which is how this surfaced.
    """
    fired: list[int] = []
    monkeypatch.setattr(
        ProcessPage, "process_jobs", lambda self: fired.append(id(self))
    )
    config = SimpleNamespace(settings=SimpleNamespace())
    main_window = QMainWindow()
    wizard = QWizard()

    # three wizard rebuilds, with no event-loop turn in between: the worst
    # case for anything relying on `deleteLater()` having happened
    for _ in range(3):
        MainWindowWizard._remove_all_pages(wizard)  # pyright: ignore[reportArgumentType]
        wizard.setPage(
            WizardPages.PROCESS_PAGE.value,
            ProcessPage(config, ProcessingContext(), main_window),  # pyright: ignore[reportArgumentType]
        )

    GSigs().wizard_process_btn_clicked.emit()

    assert len(fired) == 1


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

    deferrable = ProcessPage._deferrable_trackers(page)  # pyright: ignore[reportArgumentType]

    assert set(deferrable) == {TrackerSelection.HUNO, TrackerSelection.BEYOND_HD}


def test_nothing_is_offered_when_every_tracker_uploaded() -> None:
    page = SimpleNamespace(
        _run_outcomes={TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED},
        _deferrable_trackers=lambda: {},
    )

    # must return without prompting at all
    ProcessPage._offer_deferred_job(page)  # pyright: ignore[reportArgumentType]


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

    ProcessPage._offer_deferred_job(page)  # pyright: ignore[reportArgumentType]

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

    ProcessPage._offer_deferred_job(page)  # pyright: ignore[reportArgumentType]

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

    document = ProcessPage._build_job_document(page, directory, {TrackerSelection.HUNO})  # pyright: ignore[reportArgumentType]

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

    dialog = _open_dialog(qapp, "config")
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
    dialog = _open_dialog(qapp, "config")
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

    dialog = _open_dialog(qapp, "config")
    try:
        assert dialog.job_tree.topLevelItemCount() == 1
        dialog._accept_selection()
        assert dialog.selected_listing is None

        # "Only this config" hides the row by default, and `_apply_filter`
        # deselects whatever it hides -- reveal it and select it explicitly,
        # the way a user has to before `_accept_with_switch` can act on it.
        dialog.only_this_config.setChecked(False)
        item = dialog.job_tree.topLevelItem(0)
        assert item is not None
        item.setSelected(True)

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

    dialog = _open_dialog(qapp, "config")
    try:
        dialog._accept_selection()
        assert dialog.selected_listing is not None
        assert dialog.switch_profile_requested is False
    finally:
        dialog.deleteLater()


def _save_listing(
    working_dir: Path, name: str, *, prepared: bool, profile: str = "config"
) -> None:
    """Write a job whose document is or isn't prepared, for picker tests.

    A prepared job carries both halves: the trackers it will run and the
    frozen release for each of them. Release data on its own belongs to a
    tracker the job is holding state for rather than running.
    """
    context = (
        {
            "shared_data": {
                "selected_trackers": ["AITHER"],
                "tracker_release_data": {"AITHER": {"title": "x"}},
            }
        }
        if prepared
        else {"shared_data": {}}
    )
    store.save_job(
        store.build_job(name, JobSummary(), context, config_profile=profile),
        working_dir,
    )


def test_the_picker_shows_whether_a_job_is_prepared(
    qapp: Any, working_dir: Path, patched_working_dirs: None
) -> None:
    _save_listing(working_dir, "ready", prepared=True)

    dialog = _open_dialog(qapp, "config")
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

    dialog = _open_dialog(qapp, "config")
    try:
        dialog._delete_selected()
        assert dialog._loader is not None
        dialog._loader.wait(5000)
        qapp.processEvents()
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


def test_help_button_slot_can_carry_the_jobs_button(qapp: Any) -> None:
    """All three CustomButton slots are taken, so Jobs rides on HelpButton.

    Guards that a custom button placed in that slot really is shown when the
    layout asks for it, and hidden when a layout omits it.
    """
    wizard = QWizard()
    wizard.setPage(WizardPages.INPUT_PAGE.value, QWizardPage())
    load_button = QPushButton("Jobs", wizard)
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


class _StopBeforeProcessing(Exception):
    """Ends `process_jobs` right after the source-less notice would be logged."""


def test_the_source_less_notice_is_logged_once_per_run(
    qapp: Any, sample_media: Path, tmp_path: Path
) -> None:
    """It describes the run, not something that happened during it.

    `process_jobs` is entered once per press of the Process button -- dupe
    check, then upload, and again for Prepare -- so without a latch the same
    paragraph lands in the log repeatedly, running into whatever section was
    already there.
    """
    context = ProcessingContext()
    _populate(context, sample_media)
    context.shared_data.base_torrent = tmp_path / "base.torrent"
    sample_media.unlink()

    logged: list[str] = []
    page = cast(
        Any,
        SimpleNamespace(
            context=context,
            _source_less_notice_shown=False,
            _on_text_update=logged.append,
            _gather_tracker_data=lambda _detected: (_ for _ in ()).throw(
                _StopBeforeProcessing()
            ),
        ),
    )

    for _ in range(3):
        with pytest.raises(_StopBeforeProcessing):
            ProcessPage.process_jobs(page)

    assert len(logged) == 1
    assert "archived release package" in logged[0]


def test_the_process_page_flags_a_source_less_run(
    qapp: Any, sample_media: Path, tmp_path: Path
) -> None:
    """The banner and the log line have to agree, so they share this predicate."""
    context = ProcessingContext()
    _populate(context, sample_media)
    page = cast(Any, SimpleNamespace(context=context))

    # media present, no archive to fall back on
    assert ProcessPage._source_less_run(page) is False

    # media present and an archive carried: still a normal run
    context.shared_data.base_torrent = tmp_path / "base.torrent"
    assert ProcessPage._source_less_run(page) is False

    sample_media.unlink()
    assert ProcessPage._source_less_run(page) is True

    # gone with nothing to fall back on is not source-less, it is unusable --
    # `process_jobs` refuses that outright rather than warning about it
    context.shared_data.base_torrent = None
    assert ProcessPage._source_less_run(page) is False


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


def test_an_archive_being_extended_starts_at_the_trackers_page(
    qapp: Any, sample_media: Path
) -> None:
    """The add-trackers path would otherwise decide nothing at all.

    Tracker choice and NFO template assignment are read live from the profile
    rather than stored in the job, so a run that has to make them needs the
    wizard pages that own them -- the old straight-to-process resume skipped
    both, and the run died reading a template nobody had assigned.
    """
    context = ProcessingContext()
    _populate(context, sample_media)
    # an archive can carry prepared work for trackers an earlier run left
    # pending, which reads as prepared even though the request is for new ones
    context.shared_data.tracker_release_data[TrackerSelection.AITHER] = {
        "title": "Example 2024",
        "nfo": "the frozen nfo",
    }

    assert (
        MainWindowWizard._resume_start_page(context, adding_trackers=True)
        is WizardPages.TRACKERS_PAGE
    )


def test_a_job_saved_before_it_was_prepared_starts_at_the_trackers_page(
    qapp: Any, sample_media: Path
) -> None:
    context = ProcessingContext()
    _populate(context, sample_media)  # selected trackers, but no frozen NFOs

    assert (
        MainWindowWizard._resume_start_page(context, adding_trackers=False)
        is WizardPages.TRACKERS_PAGE
    )


def test_a_prepared_job_still_resumes_straight_to_processing(
    qapp: Any, sample_media: Path
) -> None:
    """Its titles and NFOs are frozen, so there is nothing left to choose."""
    context = ProcessingContext()
    _populate(context, sample_media)
    context.shared_data.tracker_release_data[TrackerSelection.AITHER] = {
        "title": "Example 2024",
        "nfo": "the frozen nfo",
    }

    assert (
        MainWindowWizard._resume_start_page(context, adding_trackers=False)
        is WizardPages.PROCESS_PAGE
    )


def test_an_archive_with_nothing_left_to_run_starts_at_the_trackers_page(
    qapp: Any, sample_media: Path
) -> None:
    """A spent archive keeps release data it is not going to upload.

    An upload nobody could confirm holds on to its title and NFO so that
    resolving it later still has the reviewed release to put back, while
    staying out of `selected_trackers` so nothing can send it twice. Reading
    that leftover as "prepared" resumed the job straight to the process page,
    which built no tracker row and then failed on Process with "Failed to
    generate tracker data" -- the run has to start where trackers are chosen.
    """
    context = ProcessingContext()
    _populate(context, sample_media)
    context.shared_data.selected_trackers = []
    context.shared_data.tracker_release_data[TrackerSelection.HUNO] = {
        "title": "Example 2024",
        "nfo": "held for an upload nobody could confirm",
    }

    assert context.shared_data.is_prepared() is False
    assert (
        MainWindowWizard._resume_start_page(context, adding_trackers=False)
        is WizardPages.TRACKERS_PAGE
    )


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


def test_a_pack_with_a_changed_episode_falls_back_to_hashing(
    qapp: Any, tmp_path: Path
) -> None:
    pack = tmp_path / "Pack.S01"
    pack.mkdir()
    (pack / "e01.mkv").write_bytes(b"a")
    (pack / "e02.mkv").write_bytes(b"bb")
    job_dir_path = tmp_path / "job"
    job_dir_path.mkdir()
    (job_dir_path / "base.torrent").write_bytes(b"torrent")

    context = ProcessingContext()
    context.media_input.input_path = pack
    context.media_input.file_list.append(pack / "e01.mkv")

    job = SimpleNamespace(
        name="pack",
        context={
            "base_torrent": {
                "media": str(pack),
                "fingerprints": fingerprint_files(torrent_content_files(pack)),
            }
        },
    )

    (pack / "e02.mkv").write_bytes(b"different")
    MainWindowWizard._attach_base_torrent(SimpleNamespace(), job, job_dir_path, context)  # pyright: ignore[reportArgumentType]

    assert context.shared_data.base_torrent is None


def test_an_unchanged_pack_reuses_the_stored_torrent(qapp: Any, tmp_path: Path) -> None:
    """The positive case: nothing changed, so the clone must actually happen."""
    pack = tmp_path / "Pack.S01"
    pack.mkdir()
    (pack / "e01.mkv").write_bytes(b"a")
    (pack / "e02.mkv").write_bytes(b"bb")
    job_dir_path = tmp_path / "job"
    job_dir_path.mkdir()
    stored = job_dir_path / "base.torrent"
    stored.write_bytes(b"torrent")

    context = ProcessingContext()
    context.media_input.input_path = pack
    context.media_input.file_list.append(pack / "e01.mkv")

    job = SimpleNamespace(
        name="pack",
        context={
            "base_torrent": {
                "media": str(pack),
                "fingerprints": fingerprint_files(torrent_content_files(pack)),
            }
        },
    )

    MainWindowWizard._attach_base_torrent(SimpleNamespace(), job, job_dir_path, context)  # pyright: ignore[reportArgumentType]

    assert context.shared_data.base_torrent == stored


def test_a_legacy_single_file_fingerprint_is_honoured(
    qapp: Any, tmp_path: Path
) -> None:
    """A job saved before whole-release fingerprints recorded only the first
    file -- for a single-file release that is the whole torrent, so it must
    still be trusted."""
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"a")
    job_dir_path = tmp_path / "job"
    job_dir_path.mkdir()
    stored = job_dir_path / "base.torrent"
    stored.write_bytes(b"torrent")

    context = ProcessingContext()
    context.media_input.input_path = media
    context.media_input.file_list.append(media)

    job = SimpleNamespace(
        name="movie",
        context={
            "base_torrent": {
                "media": str(media),
                "fingerprint": MediaFingerprint.of(media).to_dict(),
            }
        },
    )

    MainWindowWizard._attach_base_torrent(SimpleNamespace(), job, job_dir_path, context)  # pyright: ignore[reportArgumentType]

    assert context.shared_data.base_torrent == stored


def test_a_legacy_fingerprint_does_not_vouch_for_a_directory(
    qapp: Any, tmp_path: Path
) -> None:
    """Guards the `is_dir()` check: a pre-fix job recorded only the first
    file, which cannot prove the rest of a pack is unchanged even though that
    first file itself is untouched here."""
    pack = tmp_path / "Pack.S01"
    pack.mkdir()
    first = pack / "e01.mkv"
    first.write_bytes(b"a")
    (pack / "e02.mkv").write_bytes(b"bb")
    job_dir_path = tmp_path / "job"
    job_dir_path.mkdir()
    (job_dir_path / "base.torrent").write_bytes(b"torrent")

    context = ProcessingContext()
    context.media_input.input_path = pack
    context.media_input.file_list.append(first)

    job = SimpleNamespace(
        name="pack",
        context={
            "base_torrent": {
                "media": str(pack),
                "fingerprint": MediaFingerprint.of(first).to_dict(),
            }
        },
    )

    MainWindowWizard._attach_base_torrent(SimpleNamespace(), job, job_dir_path, context)  # pyright: ignore[reportArgumentType]

    assert context.shared_data.base_torrent is None


# --------------------------------------------------------------------------
# starting over clears the MediaInfo cache
# --------------------------------------------------------------------------
def test_starting_over_drops_mediainfo_cached_by_a_loaded_job(
    qapp: Any, sample_media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale dump would be sent to a tracker as if it described the new file."""
    from src.backend.utils import media_info_utils

    media_info_utils.cache_full_mi_str(sample_media, "dump from the previous job")

    # `reset_wizard` builds a real ProcessingContext from live settings, which
    # a stand-in has none of; the cache clear is what is under test, not that.
    monkeypatch.setattr(
        wizard_module, "create_processing_context", lambda _settings, _plugins: None
    )

    wizard = SimpleNamespace(
        config=SimpleNamespace(settings=None, plugin_manager=None),
        context=None,
        currentIdChanged=SimpleNamespace(disconnect=lambda: None),
        _remove_all_pages=lambda: None,
        _generate_new_pages=lambda: [],
        _PAGES=[],
        _insert_plugin_page=lambda: None,
        _build_wizard_pages=lambda: None,
        _set_start_page=lambda: None,
        _connect_current_id_changed=lambda: None,
        _set_disabled=lambda _value: None,
        next_button=SimpleNamespace(setText=lambda _text: None),
        process_button=SimpleNamespace(setText=lambda _text: None),
        _apply_button_layout=lambda _buttons: None,
        starting_buttons=(),
        restart=lambda: None,
        _sync_button_layout=lambda: None,
    )

    MainWindowWizard.reset_wizard(wizard)  # pyright: ignore[reportArgumentType]

    assert media_info_utils._FULL_MI_STR_CACHE == {}


def test_a_job_name_with_markup_is_escaped_in_the_log(qapp: Any) -> None:
    written: list[str] = []
    page = SimpleNamespace(_on_text_update=written.append)

    ProcessPage._announce_saved_job(page, "<b>bold</b> job")  # pyright: ignore[reportArgumentType]

    assert "&lt;b&gt;" in written[0]
    assert "<b>bold</b> job" not in written[0]


def test_a_job_name_with_markup_is_rendered_as_plain_text_in_the_saved_box(
    qapp: Any, working_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The save confirmation box must show the job name verbatim, not interpret
    markup. Verifies that the box uses PlainText format so angle brackets do
    not flip it into rich-text mode.
    """
    from PySide6.QtGui import Qt

    captured_boxes: list[Any] = []

    class MockMessageBox:
        """Mock that accepts any parent and captures the instance."""

        Icon = QMessageBox.Icon
        Accepted = QMessageBox.DialogCode.Accepted

        def __init__(self, parent: Any = None) -> None:
            self.parent_obj = parent
            self.title = ""
            self.icon = None
            self.text_format = Qt.TextFormat.AutoText
            self.icon_val = None
            self.text_val = ""
            self.exec_called = False
            captured_boxes.append(self)

        def setWindowTitle(self, title: str) -> None:
            self.title = title

        def setTextFormat(self, fmt: Any) -> None:
            self.text_format = fmt

        def textFormat(self) -> Any:
            return self.text_format

        def setIcon(self, icon: Any) -> None:
            self.icon_val = icon

        def setText(self, text: str) -> None:
            self.text_val = text

        def text(self) -> str:
            return self.text_val

        def exec(self) -> int:
            self.exec_called = True
            return self.Accepted

    monkeypatch.setattr(process_module, "QMessageBox", MockMessageBox)

    # Mock the dependencies to reach the save success path.
    page = SimpleNamespace()
    page.context = ProcessingContext()
    # A real directory, because `_save_job` really creates one: `build_job` and
    # `save_job` are mocked below but `job_dir(..., ensure_exists=True)` is not,
    # and it mkdirs. A hardcoded absolute path here resolves against the current
    # drive on Windows and quietly writes outside the repo, while on Linux it
    # raises PermissionError -- green locally, red on CI.
    page.config = SimpleNamespace(
        settings=SimpleNamespace(general=SimpleNamespace(working_dir=working_dir)),
        program=SimpleNamespace(current_config="test"),
    )
    page._announce_saved_job = lambda name: None
    page._build_job_document = lambda *_: {}
    page._job_summary = lambda *_: JobSummary()
    page._default_job_name = lambda: "test"
    page._get_job_name = lambda *_: ("<b>bold</b> job", True)
    page._on_text_update = lambda *_: None

    # Mock media validation.
    monkeypatch.setattr(
        "src.context.processing_context.MediaInputPayload.require_existing_media_paths",
        lambda *_, **__: None,
    )

    monkeypatch.setattr(
        "src.frontend.wizards.process.build_job",
        lambda **_: SimpleNamespace(
            name="<b>bold</b> job", job_id="test-id", context={}
        ),
    )
    monkeypatch.setattr(
        "src.frontend.wizards.process.save_job",
        lambda *_: Path("/saved/job"),
    )

    # Drive the success path of _save_job.
    context = page.context
    context.media_input.input_path = Path("/test.mkv")

    ProcessPage._save_job(page)  # pyright: ignore[reportArgumentType]

    # The message box should have been created.
    assert len(captured_boxes) == 1
    box = captured_boxes[0]
    assert box.textFormat() == Qt.TextFormat.PlainText
    assert "<b>bold</b> job" in box.text()
    # The rest of the confirmation wording, pinned so a rename silently
    # reverting "Jobs" (as already happened once on this branch) is caught
    # here rather than only in the wizard button's tooltip.
    assert "Use 'Jobs' on the start page to come back to it." in box.text()
    # A regression that stopped displaying the box entirely -- e.g. building
    # `saved_box` and never calling `.exec()` -- would leave every assertion
    # above green. This is what catches that.
    assert box.exec_called is True
    # Pins the working directory to the fixture: revert it to a hardcoded path
    # and this fails here rather than only on a Linux runner.
    assert (working_dir / "jobs" / "test-id").is_dir()
