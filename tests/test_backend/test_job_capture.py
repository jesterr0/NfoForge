"""Saving a configured run as a job, and a finished run as an archive."""

from pathlib import Path

import pytest
from torf import Torrent

from nfoforge.backend.jobs import (
    archive_completed_run,
    build_job_document,
    default_job_name,
    first_generated_torrent,
    save_new_job,
    store,
    update_prepared_archive,
)
from nfoforge.backend.upload_retry import TrackerRunOutcome
from nfoforge.backend.utils.media_info_utils import clear_full_mi_str_cache
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.enums.image_host import ImageHost, ImageSource
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.packages.custom_types import (
    ImageHostRef,
    ImageUploadData,
    ImageUploadFromTo,
)
from tests.job_helpers import populate_context, write_sample_media


@pytest.fixture(autouse=True)
def _clear_mi_cache() -> None:
    clear_full_mi_str_cache()


@pytest.fixture
def working_dir(tmp_path: Path) -> Path:
    return tmp_path / "nfoforge"


@pytest.fixture
def sample_media(tmp_path: Path) -> Path:
    return write_sample_media(tmp_path)


def _write_base_torrent(context: ProcessingContext, media: Path) -> Path:
    context.media_input.require_working_dir().mkdir()
    base = context.media_input.require_working_dir() / "Example.Movie.2024.base.torrent"
    torrent = Torrent(path=media, private=True)
    torrent.generate()
    torrent.write(base)
    return base


def _archive(
    context: ProcessingContext,
    outcomes: dict[TrackerSelection, TrackerRunOutcome],
    working_dir: Path,
) -> None:
    archive_completed_run(
        context, outcomes, working_dir=working_dir, config_profile="config"
    )


# --------------------------------------------------------------------------
# saving a configured run
# --------------------------------------------------------------------------
def test_default_job_name_prefers_title_and_year(sample_media: Path) -> None:
    context = ProcessingContext()
    populate_context(context, sample_media)

    assert default_job_name(context) == "Example (2024)"

    context.media_search.title = None
    assert default_job_name(context) == "Example.Movie.2024"


def test_the_base_torrent_is_found_beside_the_working_files(
    sample_media: Path,
) -> None:
    context = ProcessingContext()
    populate_context(context, sample_media)
    assert first_generated_torrent(context) is None

    base = _write_base_torrent(context, sample_media)

    assert first_generated_torrent(context) == base


def test_a_saved_job_round_trips(sample_media: Path, working_dir: Path) -> None:
    context = ProcessingContext()
    populate_context(context, sample_media)
    context.shared_data.loaded_images[0].write_bytes(b"screenshot")

    job, path = save_new_job(
        context, name="My job", working_dir=working_dir, config_profile="config"
    )

    listing = store.list_jobs([working_dir])
    assert [item.name for item in listing] == ["My job"]
    assert store.load_job(path).job_id == job.job_id
    assert job.summary.trackers == [str(TrackerSelection.AITHER)]


def test_a_job_that_fails_to_save_leaves_nothing_behind(
    sample_media: Path, working_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = ProcessingContext()
    populate_context(context, sample_media)

    def fail(*_args: object) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr("nfoforge.backend.jobs.capture.save_job", fail)

    with pytest.raises(OSError, match="disk full"):
        save_new_job(
            context, name="x", working_dir=working_dir, config_profile="config"
        )

    assert not any(store.jobs_dir(working_dir).iterdir())


def test_content_size_is_recorded_even_without_a_base_torrent(
    sample_media: Path, working_dir: Path
) -> None:
    """Two trackers size a disc release off the filesystem when it is absent.

    `beyondhd` and `passthepopcorn` both fall back to
    `input_path.stat().st_size`, which a source-less run cannot do -- and save
    time is the last moment the media is guaranteed to be there to measure.
    """
    context = ProcessingContext()
    populate_context(context, sample_media)
    context.shared_data.loaded_images[0].write_bytes(b"screenshot")
    directory = working_dir / "jobs" / "abc"
    directory.mkdir(parents=True)

    document = build_job_document(context, directory, None)

    assert "base_torrent" not in document
    assert document["media_input"]["content_size"] == sample_media.stat().st_size


def test_a_deferred_job_only_stores_nfos_for_the_trackers_it_keeps(
    sample_media: Path, tmp_path: Path
) -> None:
    """A dropped tracker's NFO left in the folder implies the job still covers it."""
    context = ProcessingContext()
    populate_context(context, sample_media)
    context.shared_data.tracker_image_hosts[TrackerSelection.HUNO] = ImageUploadFromTo(
        ImageSource.IMAGES, ImageHostRef(ImageHost.CHEVERETO_V3)
    )
    context.shared_data.tracker_release_data = {
        TrackerSelection.AITHER: {"title": "a", "nfo": "already uploaded"},
        TrackerSelection.HUNO: {"title": "h", "nfo": "still to go"},
    }
    directory = tmp_path / "job"
    directory.mkdir()

    document = build_job_document(context, directory, {TrackerSelection.HUNO})

    assert set(document["shared_data"]["tracker_release_data"]) == {"HUNO"}
    assert {path.name for path in (directory / "nfo").iterdir()} == {"huno.txt"}


# --------------------------------------------------------------------------
# archiving a finished run
# --------------------------------------------------------------------------
def test_completed_upload_is_kept_as_a_source_less_archive(
    sample_media: Path, working_dir: Path
) -> None:
    context = ProcessingContext()
    populate_context(context, sample_media)
    context.shared_data.tracker_release_data = {
        TrackerSelection.AITHER: {"title": "Example", "nfo": "release nfo"}
    }
    context.shared_data.loaded_images[0].write_bytes(b"screenshot")
    _write_base_torrent(context, sample_media)

    _archive(
        context, {TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED}, working_dir
    )

    listings = store.list_jobs([working_dir])
    assert len(listings) == 1
    assert listings[0].archived
    assert listings[0].source_less_ready
    saved = store.load_job(listings[0].path)
    assert saved.uploaded_trackers == [TrackerSelection.AITHER.name]
    assert context.loaded_job_archived
    assert context.loaded_job_path == listings[0].path

    sample_media.unlink()

    assert store.list_jobs([working_dir])[0].source_less_ready


def test_adding_trackers_keeps_one_left_pending_by_an_earlier_run(
    sample_media: Path, working_dir: Path
) -> None:
    """Adding a tracker must not discard what an earlier run left unfinished.

    The outcomes only cover the trackers of the run that just ended, so
    narrowing the archive to them drops a tracker that failed last time -- its
    prepared title and NFO go with it, and the sidecars are pruned. The user
    would have no way back except preparing that tracker over again, and no
    indication it happened.
    """
    context = ProcessingContext()
    populate_context(context, sample_media)
    context.shared_data.tracker_release_data = {
        TrackerSelection.AITHER: {"title": "Example", "nfo": "aither nfo"},
        TrackerSelection.HUNO: {"title": "Example", "nfo": "huno nfo"},
    }
    context.shared_data.loaded_images[0].write_bytes(b"screenshot")
    _write_base_torrent(context, sample_media)

    _archive(
        context,
        {
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOAD_FAILED,
        },
        working_dir,
    )
    path = store.list_jobs([working_dir])[0].path
    assert store.load_job(path).summary.trackers == [str(TrackerSelection.HUNO)]

    # Now add LST to that archive. Resuming clears the image-host map and
    # re-fills it with only the additions, exactly as `_load_job` does, so HUNO
    # has no row in this run at all. The first archive already pointed the
    # context at itself.
    context.shared_data.tracker_release_data[TrackerSelection.LST] = {
        "title": "Example",
        "nfo": "lst nfo",
    }
    context.shared_data.tracker_image_hosts.clear()
    context.shared_data.tracker_image_hosts[TrackerSelection.LST] = ImageUploadFromTo(
        ImageSource.IMAGES, ImageHostRef(ImageHost.CHEVERETO_V3)
    )

    _archive(context, {TrackerSelection.LST: TrackerRunOutcome.UPLOADED}, working_dir)

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
    populate_context(context, sample_media)
    context.shared_data.selected_trackers = [
        TrackerSelection.AITHER,
        TrackerSelection.HUNO,
    ]
    context.shared_data.tracker_image_hosts[TrackerSelection.HUNO] = ImageUploadFromTo(
        ImageSource.IMAGES, ImageHostRef(ImageHost.PIXHOST)
    )
    context.shared_data.tracker_release_data = {
        TrackerSelection.AITHER: {"title": "Example", "nfo": "aither nfo"},
        TrackerSelection.HUNO: {"title": "Example", "nfo": "huno nfo"},
    }
    context.shared_data.loaded_images[0].write_bytes(b"screenshot")
    context.media_input.require_working_dir().mkdir()

    _archive(
        context,
        {
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED,
            TrackerSelection.HUNO: TrackerRunOutcome.MAY_HAVE_UPLOADED,
        },
        working_dir,
    )

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
    populate_context(context, sample_media)
    context.shared_data.tracker_release_data = {
        TrackerSelection.AITHER: {"title": "Example", "nfo": "aither nfo"}
    }
    context.shared_data.loaded_images[0].write_bytes(b"screenshot")
    context.media_input.require_working_dir().mkdir()
    uploaded = {0: ImageUploadData(url="https://pixhost/0.png", medium_url=None)}
    context.shared_data.uploaded_images[TrackerSelection.AITHER] = dict(uploaded)
    context.shared_data.uploaded_image_hosts[TrackerSelection.AITHER] = ImageHostRef(
        ImageHost.PIXHOST
    )
    context.shared_data.uploaded_images_by_host[ImageHostRef(ImageHost.PIXHOST)] = dict(
        uploaded
    )

    _archive(
        context, {TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED}, working_dir
    )

    saved = store.load_job(store.list_jobs([working_dir])[0].path)
    shared = saved.context["shared_data"]
    assert shared["uploaded_images"] == {}
    assert shared["uploaded_images_by_host"] == [
        {
            "name": "PIXHOST",
            "type": "ImageHostRef",
            # empty for every host but a Chevereto instance, the only kind
            # that holds more than one site
            "instance": "",
            "images": {"0": {"url": "https://pixhost/0.png", "medium_url": None}},
        }
    ]


def test_an_archive_that_fails_to_write_is_removed(
    sample_media: Path, working_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = ProcessingContext()
    populate_context(context, sample_media)
    context.shared_data.loaded_images[0].write_bytes(b"screenshot")

    def fail(*_args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("nfoforge.backend.jobs.capture.write_job_document", fail)

    with pytest.raises(OSError, match="disk full"):
        _archive(
            context,
            {TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED},
            working_dir,
        )

    assert not any(store.jobs_dir(working_dir).iterdir())
    assert context.loaded_job_path is None


# --------------------------------------------------------------------------
# updating a prepared archive
# --------------------------------------------------------------------------
def test_a_prepared_plain_job_is_not_silently_overwritten(
    sample_media: Path, working_dir: Path
) -> None:
    """Only an archive is updated in place.

    Preparing an ordinary saved job keeps the named save it always had -- the
    in-place path exists for archives, which may have no source left to capture
    MediaInfo from.
    """
    context = ProcessingContext()
    populate_context(context, sample_media)
    context.loaded_job_path = working_dir / "some-job"
    context.loaded_job_archived = False

    assert update_prepared_archive(context) is None
