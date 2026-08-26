"""Coverage for what a resumed job reuses instead of redoing.

These guard the two most expensive steps of a run -- uploading screenshots to an
image host, and hashing the media into a torrent -- against being repeated when
a job already carries the result.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.backend.jobs import context_from_dict, load_job, read_job_asset
from src.backend.process import ProcessBackEnd
from src.context.processing_context import ProcessingContext
from src.enums.image_host import ImageHost, ImageSource
from src.enums.tracker_selection import TrackerSelection
from src.exceptions import ImageHostError, ImageUploadError
from src.packages.custom_types import ImageHostRef, ImageUploadData, ImageUploadFromTo
from tests.conftest import SourceLessBundle


def _backend() -> ProcessBackEnd:
    return cast(ProcessBackEnd, object.__new__(ProcessBackEnd))


def _uploaded() -> dict[int, ImageUploadData]:
    return {0: ImageUploadData(url="https://host/a.png", medium_url=None)}


def _context_with_upload(
    tracker: TrackerSelection, host: ImageHostRef | ImageSource
) -> ProcessingContext:
    context = ProcessingContext()
    context.shared_data.uploaded_images[tracker] = _uploaded()
    context.shared_data.uploaded_image_hosts[tracker] = host
    return context


# --------------------------------------------------------------------------
# image reuse
# --------------------------------------------------------------------------
def test_images_are_reused_when_the_destination_is_unchanged() -> None:
    context = _context_with_upload(
        TrackerSelection.AITHER, ImageHostRef(ImageHost.CHEVERETO_V3)
    )

    reusable = ProcessBackEnd._reusable_uploaded_images(
        context, TrackerSelection.AITHER, ImageHostRef(ImageHost.CHEVERETO_V3)
    )

    assert reusable == _uploaded()


def test_images_are_not_reused_after_the_image_host_changes() -> None:
    """The stored URLs point at a host this tracker no longer uploads to."""
    context = _context_with_upload(
        TrackerSelection.AITHER, ImageHostRef(ImageHost.CHEVERETO_V3)
    )

    reusable = ProcessBackEnd._reusable_uploaded_images(
        context, TrackerSelection.AITHER, ImageHostRef(ImageHost.PIXHOST)
    )

    assert reusable is None


def test_a_tracker_without_recorded_uploads_gets_none() -> None:
    """Another tracker's per-tracker record says nothing about this one.

    Reusing across trackers is keyed on the *host*, not on the fact that some
    other tracker uploaded -- see the by-host tests below.
    """
    context = _context_with_upload(
        TrackerSelection.AITHER, ImageHostRef(ImageHost.CHEVERETO_V3)
    )

    reusable = ProcessBackEnd._reusable_uploaded_images(
        context, TrackerSelection.HUNO, ImageHostRef(ImageHost.CHEVERETO_V3)
    )

    assert reusable is None


# --------------------------------------------------------------------------
# reuse by host: what a tracker added after the run can still serve
# --------------------------------------------------------------------------
def test_a_new_tracker_reuses_urls_the_job_holds_for_that_host() -> None:
    """The images are the host's, not the tracker's.

    A tracker added to an archive after the run that uploaded the screenshots
    has no per-tracker record of its own. Sending the same files to a host that
    already has them wastes an upload -- and a source-less archive has no files
    to send at all.
    """
    context = ProcessingContext()
    context.shared_data.uploaded_images_by_host[
        ImageHostRef(ImageHost.CHEVERETO_V3)
    ] = _uploaded()

    reusable = ProcessBackEnd._reusable_uploaded_images(
        context, TrackerSelection.HUNO, ImageHostRef(ImageHost.CHEVERETO_V3)
    )

    assert reusable == _uploaded()


def test_a_new_tracker_pointed_at_another_host_still_uploads() -> None:
    context = ProcessingContext()
    context.shared_data.uploaded_images_by_host[
        ImageHostRef(ImageHost.CHEVERETO_V3)
    ] = _uploaded()

    assert (
        ProcessBackEnd._reusable_uploaded_images(
            context, TrackerSelection.HUNO, ImageHostRef(ImageHost.PIXHOST)
        )
        is None
    )
    assert ProcessBackEnd.needs_local_images(
        context, TrackerSelection.HUNO, ImageHostRef(ImageHost.PIXHOST)
    )


def test_moving_a_tracker_to_a_host_the_job_already_served_reuses_it() -> None:
    """Its own record is the wrong host's; the job's by-host record is not."""
    context = _context_with_upload(
        TrackerSelection.AITHER, ImageHostRef(ImageHost.CHEVERETO_V3)
    )
    pixhost = {0: ImageUploadData(url="https://pixhost/a.png", medium_url=None)}
    context.shared_data.uploaded_images_by_host[ImageHostRef(ImageHost.PIXHOST)] = dict(
        pixhost
    )

    reusable = ProcessBackEnd._reusable_uploaded_images(
        context, TrackerSelection.AITHER, ImageHostRef(ImageHost.PIXHOST)
    )

    assert reusable == pixhost


def test_by_host_reuse_is_a_copy_not_the_stored_mapping() -> None:
    context = ProcessingContext()
    context.shared_data.uploaded_images_by_host[
        ImageHostRef(ImageHost.CHEVERETO_V3)
    ] = _uploaded()

    reusable = ProcessBackEnd._reusable_uploaded_images(
        context, TrackerSelection.HUNO, ImageHostRef(ImageHost.CHEVERETO_V3)
    )
    assert reusable is not None
    reusable[99] = ImageUploadData(url="https://host/injected.png", medium_url=None)

    assert (
        99
        not in context.shared_data.uploaded_images_by_host[
            ImageHostRef(ImageHost.CHEVERETO_V3)
        ]
    )


def test_by_host_urls_survive_narrowing_a_job_to_no_trackers() -> None:
    """The failure this closes: a fully successful run archived zero URLs.

    Every per-tracker map is narrowed away when nothing is left pending, so
    before this the archive a completed run left behind could not serve a
    single image to a tracker added later.
    """
    from src.backend.jobs.codec import filter_context_document

    document = {
        "shared_data": {
            "selected_trackers": ["AITHER"],
            "uploaded_images": {"AITHER": {}},
            "uploaded_images_by_host": [
                {"name": "PIXHOST", "type": "ImageHost", "images": {}}
            ],
        }
    }

    filtered = filter_context_document(document, set())

    assert filtered["shared_data"]["uploaded_images"] == {}
    assert filtered["shared_data"]["uploaded_images_by_host"] == [
        {"name": "PIXHOST", "type": "ImageHost", "images": {}}
    ]


def test_by_host_urls_round_trip_through_the_codec(tmp_path: Path) -> None:
    from src.backend.jobs.codec import context_from_dict, context_to_dict

    source = ProcessingContext()
    source.media_input.input_path = tmp_path / "media.mkv"
    source.shared_data.uploaded_images_by_host[ImageHostRef(ImageHost.PIXHOST)] = (
        _uploaded()
    )

    restored = ProcessingContext()
    context_from_dict(context_to_dict(source, {}), restored)

    assert restored.shared_data.uploaded_images_by_host == {
        ImageHostRef(ImageHost.PIXHOST): _uploaded()
    }


@pytest.mark.parametrize(
    "destination",
    [ImageHostRef(ImageHost.DISABLED), ImageSource.URLS, ImageSource.IMAGES],
)
def test_non_host_destinations_are_never_reused(destination: Any) -> None:
    """Nothing was uploaded for these, so there is nothing to reuse."""
    context = _context_with_upload(TrackerSelection.AITHER, destination)

    assert (
        ProcessBackEnd._reusable_uploaded_images(
            context, TrackerSelection.AITHER, destination
        )
        is None
    )


def test_reused_images_are_a_copy_not_the_stored_mapping() -> None:
    """Mutating a run's image map must not corrupt what the job recorded."""
    context = _context_with_upload(
        TrackerSelection.AITHER, ImageHostRef(ImageHost.CHEVERETO_V3)
    )

    reusable = ProcessBackEnd._reusable_uploaded_images(
        context, TrackerSelection.AITHER, ImageHostRef(ImageHost.CHEVERETO_V3)
    )
    assert reusable is not None
    reusable[99] = ImageUploadData(url="https://host/injected.png", medium_url=None)

    assert 99 not in context.shared_data.uploaded_images[TrackerSelection.AITHER]


# --------------------------------------------------------------------------
# "does this tracker still need the screenshot files on disk?"
# --------------------------------------------------------------------------
def test_a_tracker_with_reusable_urls_needs_no_local_files() -> None:
    context = _context_with_upload(
        TrackerSelection.AITHER, ImageHostRef(ImageHost.CHEVERETO_V3)
    )

    assert not ProcessBackEnd.needs_local_images(
        context, TrackerSelection.AITHER, ImageHostRef(ImageHost.CHEVERETO_V3)
    )


@pytest.mark.parametrize(
    "destination", [ImageHostRef(ImageHost.DISABLED), ImageSource.URLS]
)
def test_a_tracker_that_uploads_nothing_needs_no_local_files(
    destination: Any,
) -> None:
    """Regression guard: these have no recorded uploads, but need no files.

    Counting them as needing screenshots made the queue refuse jobs over
    images they were never going to send.
    """
    context = ProcessingContext()

    assert not ProcessBackEnd.needs_local_images(
        context, TrackerSelection.AITHER, destination
    )


def test_changing_the_image_host_puts_a_tracker_back_on_local_files() -> None:
    """Regression guard: the stored URLs are the old host's, so they cannot be
    reused -- a check that only asked "are there any recorded uploads?" let a
    job with missing screenshots through and uploaded none."""
    context = _context_with_upload(
        TrackerSelection.AITHER, ImageHostRef(ImageHost.CHEVERETO_V3)
    )

    assert ProcessBackEnd.needs_local_images(
        context, TrackerSelection.AITHER, ImageHostRef(ImageHost.PIXHOST)
    )


def test_a_tracker_with_no_uploads_yet_needs_local_files() -> None:
    context = ProcessingContext()

    assert ProcessBackEnd.needs_local_images(
        context, TrackerSelection.AITHER, ImageHostRef(ImageHost.CHEVERETO_V3)
    )


def test_empty_recorded_uploads_do_not_count_as_reusable() -> None:
    context = ProcessingContext()
    context.shared_data.uploaded_images[TrackerSelection.AITHER] = {}
    context.shared_data.uploaded_image_hosts[TrackerSelection.AITHER] = ImageHostRef(
        ImageHost.CHEVERETO_V3
    )

    assert (
        ProcessBackEnd._reusable_uploaded_images(
            context, TrackerSelection.AITHER, ImageHostRef(ImageHost.CHEVERETO_V3)
        )
        is None
    )


# --------------------------------------------------------------------------
# recording what was uploaded, while it is still there to record
# --------------------------------------------------------------------------
def _image_backend(
    upload_results: dict[ImageHost, dict[int, ImageUploadData]],
) -> ProcessBackEnd:
    """A backend wired up for `handle_images_for_trackers` and nothing else."""
    backend = object.__new__(ProcessBackEnd)
    backend.config = cast(
        Any,
        SimpleNamespace(
            settings=SimpleNamespace(
                screenshots=SimpleNamespace(
                    optimize_generated_images=False,
                    optimize_downloaded_images=False,
                )
            )
        ),
    )

    async def upload(*_args: Any, **_kwargs: Any) -> Any:
        return upload_results

    backend.handle_image_upload = upload  # pyright: ignore[reportAttributeAccessIssue]
    return cast(ProcessBackEnd, backend)


def _process_dict(*trackers: tuple[TrackerSelection, ImageHostRef]) -> dict[str, Any]:
    return {
        tracker.value: {"image_host_data": ImageUploadFromTo(ImageSource.IMAGES, host)}
        for tracker, host in trackers
    }


def test_a_hosts_uploads_are_recorded_before_another_hosts_failure(
    tmp_path: Path,
) -> None:
    """One incomplete batch used to throw away every batch that succeeded.

    `assert_all_images_uploaded` raises out of the whole function, and the
    recording only happened at the very end -- so a run where one host dropped
    an image lost the URLs for every other host it had just paid to upload to,
    and the next attempt uploaded them all over again.
    """
    context = ProcessingContext()
    context.shared_data.loaded_images = [tmp_path / "shot.png"]
    good = {0: ImageUploadData(url="https://pixhost/0.png", medium_url=None)}
    bad = {0: ImageUploadData(url=None, medium_url=None)}
    backend = _image_backend(
        {ImageHostRef(ImageHost.PIXHOST): good, ImageHostRef(ImageHost.LENSDUMP): bad}
    )

    with pytest.raises(ImageUploadError):
        backend.handle_images_for_trackers(
            context=context,
            process_dict=_process_dict(
                (TrackerSelection.AITHER, ImageHostRef(ImageHost.PIXHOST)),
                (TrackerSelection.HUNO, ImageHostRef(ImageHost.LENSDUMP)),
            ),
            queued_text_update=lambda _text: None,
            progress_bar_cb=lambda _value: None,
        )

    assert (
        context.shared_data.uploaded_images_by_host[ImageHostRef(ImageHost.PIXHOST)]
        == good
    )


def test_no_local_images_names_the_hosts_the_job_can_still_serve(
    tmp_path: Path,
) -> None:
    """Uploading nothing at all is not a supported outcome here.

    The bundle's screenshots exist -- as URLs on a host it already used. A run
    pointed somewhere else is one combo-box change away from working, so it
    says which hosts would work rather than quietly producing a release with
    no images. Downloading its own images back to re-upload them elsewhere is
    deliberately not done.
    """
    context = ProcessingContext()
    context.shared_data.loaded_images = None
    context.shared_data.uploaded_images_by_host[ImageHostRef(ImageHost.PIXHOST)] = {
        0: ImageUploadData(url="https://pixhost/0.png", medium_url=None)
    }
    backend = _image_backend({})

    with pytest.raises(ImageHostError) as excinfo:
        backend.handle_images_for_trackers(
            context=context,
            process_dict=_process_dict(
                (TrackerSelection.HUNO, ImageHostRef(ImageHost.LENSDUMP))
            ),
            queued_text_update=lambda _text: None,
            progress_bar_cb=lambda _value: None,
        )

    assert "Pixhost" in str(excinfo.value)
    assert "Lensdump" in str(excinfo.value)


def test_no_local_images_and_no_stored_urls_still_runs_without_images(
    tmp_path: Path,
) -> None:
    """A release genuinely without screenshots is supported and must stay so."""
    context = ProcessingContext()
    context.shared_data.loaded_images = None
    backend = _image_backend({})

    result = backend.handle_images_for_trackers(
        context=context,
        process_dict=_process_dict(
            (TrackerSelection.HUNO, ImageHostRef(ImageHost.LENSDUMP))
        ),
        queued_text_update=lambda _text: None,
        progress_bar_cb=lambda _value: None,
    )

    assert result == {}


# --------------------------------------------------------------------------
# the whole point, against a bundle with neither media nor screenshots
# --------------------------------------------------------------------------
def _restored(bundle: SourceLessBundle) -> ProcessingContext:
    job = load_job(bundle.directory)
    context = ProcessingContext()
    context_from_dict(
        job.context, context, lambda name: read_job_asset(bundle.directory, name)
    )
    return context


def test_a_source_less_bundle_serves_a_new_tracker_on_a_host_it_already_used(
    source_less_bundle: SourceLessBundle,
) -> None:
    """No media, no local screenshots, a tracker that was never part of the run.

    The bundle carries that host's URLs, so the run has everything it needs and
    must not upload -- there is nothing on disk left to upload.
    """
    source_less_bundle.strip_images()
    context = _restored(source_less_bundle)
    context.shared_data.loaded_images = None
    messages: list[str] = []

    result = _image_backend({}).handle_images_for_trackers(
        context=context,
        process_dict=_process_dict(
            (TrackerSelection.HUNO, ImageHostRef(ImageHost.PIXHOST))
        ),
        queued_text_update=messages.append,
        progress_bar_cb=lambda _value: None,
    )

    assert result[TrackerSelection.HUNO][0].url == "https://pixhost/0.png"
    assert any("Reusing 2 already-uploaded" in message for message in messages)


def test_a_source_less_bundle_refuses_a_host_it_cannot_serve(
    source_less_bundle: SourceLessBundle,
) -> None:
    """And says which host would have worked, rather than uploading nothing."""
    source_less_bundle.strip_images()
    context = _restored(source_less_bundle)
    context.shared_data.loaded_images = None

    with pytest.raises(ImageHostError) as excinfo:
        _image_backend({}).handle_images_for_trackers(
            context=context,
            process_dict=_process_dict(
                (TrackerSelection.HUNO, ImageHostRef(ImageHost.LENSDUMP))
            ),
            queued_text_update=lambda _text: None,
            progress_bar_cb=lambda _value: None,
        )

    assert "Pixhost" in str(excinfo.value)


# --------------------------------------------------------------------------
# base torrent reuse
# --------------------------------------------------------------------------
def _process_trackers_kwargs(context: ProcessingContext) -> dict[str, Any]:
    from unittest.mock import MagicMock

    return {
        "process_dict": {},
        "queued_status_update": MagicMock(),
        "queued_text_update": MagicMock(),
        "queued_text_update_replace_last_line": MagicMock(),
        "progress_bar_cb": MagicMock(),
        "caught_error": MagicMock(),
        "context": context,
    }


def _backend_for_torrent_seed() -> ProcessBackEnd:
    backend = object.__new__(ProcessBackEnd)
    backend.config = cast(
        Any,
        SimpleNamespace(
            settings=SimpleNamespace(
                general=SimpleNamespace(
                    timeout=60,
                    enable_prompt_overview=False,
                ),
                torrent_clients=SimpleNamespace(
                    qbittorrent=SimpleNamespace(enabled=False)
                ),
            )
        ),
    )
    backend.template_selector_be = cast(Any, SimpleNamespace(load_templates=lambda: {}))
    return cast(ProcessBackEnd, backend)


def test_a_carried_torrent_is_announced_and_seeds_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a base already in hand the run must not hash the media again."""
    torrent = tmp_path / "base.torrent"
    torrent.write_bytes(b"d8:announce")
    context = ProcessingContext()
    context.shared_data.base_torrent = torrent
    context.media_input.input_path = tmp_path / "media.mkv"

    backend = _backend_for_torrent_seed()
    monkeypatch.setattr(
        backend, "handle_images_for_trackers", lambda *_a, **_k: {}, raising=False
    )
    monkeypatch.setattr(
        backend, "disconnect_from_clients", lambda *_a, **_k: None, raising=False
    )

    kwargs = _process_trackers_kwargs(context)
    backend.process_trackers(**kwargs)

    announced = "".join(
        str(call.args[0]) for call in kwargs["queued_text_update"].call_args_list
    )
    assert "Reusing the torrent saved with this job" in announced


def test_a_missing_carried_torrent_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = ProcessingContext()
    context.shared_data.base_torrent = tmp_path / "gone.torrent"
    context.media_input.input_path = tmp_path / "media.mkv"

    backend = _backend_for_torrent_seed()
    monkeypatch.setattr(
        backend, "handle_images_for_trackers", lambda *_a, **_k: {}, raising=False
    )
    monkeypatch.setattr(
        backend, "disconnect_from_clients", lambda *_a, **_k: None, raising=False
    )

    kwargs = _process_trackers_kwargs(context)
    backend.process_trackers(**kwargs)

    announced = "".join(
        str(call.args[0]) for call in kwargs["queued_text_update"].call_args_list
    )
    assert "Reusing the torrent" not in announced


def test_tracker_image_hosts_survive_a_round_trip_with_uploads(
    tmp_path: Path,
) -> None:
    """Recorded uploads must be narrowed alongside the trackers they belong to."""
    from src.backend.jobs.codec import filter_context_document

    document = {
        "shared_data": {
            "selected_trackers": ["AITHER", "HUNO"],
            "tracker_image_hosts": {"AITHER": {}, "HUNO": {}},
            "uploaded_images": {"AITHER": {}, "HUNO": {}},
            "uploaded_image_hosts": {"AITHER": {}, "HUNO": {}},
        }
    }

    filtered = filter_context_document(document, {TrackerSelection.HUNO})

    shared = filtered["shared_data"]
    assert list(shared["tracker_image_hosts"]) == ["HUNO"]
    assert list(shared["uploaded_images"]) == ["HUNO"]
    assert list(shared["uploaded_image_hosts"]) == ["HUNO"]


def test_uploaded_images_round_trip_through_the_codec(tmp_path: Path) -> None:
    from src.backend.jobs.codec import context_from_dict, context_to_dict

    source = ProcessingContext()
    source.media_input.input_path = tmp_path / "media.mkv"
    source.shared_data.uploaded_images[TrackerSelection.AITHER] = _uploaded()
    source.shared_data.uploaded_image_hosts[TrackerSelection.AITHER] = ImageHostRef(
        ImageHost.CHEVERETO_V3
    )
    source.shared_data.tracker_image_hosts[TrackerSelection.AITHER] = ImageUploadFromTo(
        ImageSource.IMAGES, ImageHostRef(ImageHost.CHEVERETO_V3)
    )

    restored = ProcessingContext()
    context_from_dict(context_to_dict(source, {}), restored)

    assert restored.shared_data.uploaded_images == {
        TrackerSelection.AITHER: _uploaded()
    }
    assert restored.shared_data.uploaded_image_hosts == {
        TrackerSelection.AITHER: ImageHostRef(ImageHost.CHEVERETO_V3)
    }
