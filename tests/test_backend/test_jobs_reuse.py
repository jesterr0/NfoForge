"""Coverage for what a resumed job reuses instead of redoing.

These guard the two most expensive steps of a run -- uploading screenshots to an
image host, and hashing the media into a torrent -- against being repeated when
a job already carries the result.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.backend.process import ProcessBackEnd
from src.context.processing_context import ProcessingContext
from src.enums.image_host import ImageHost, ImageSource
from src.enums.tracker_selection import TrackerSelection
from src.packages.custom_types import ImageUploadData, ImageUploadFromTo


def _backend() -> ProcessBackEnd:
    return cast(ProcessBackEnd, object.__new__(ProcessBackEnd))


def _uploaded() -> dict[int, ImageUploadData]:
    return {0: ImageUploadData(url="https://host/a.png", medium_url=None)}


def _context_with_upload(
    tracker: TrackerSelection, host: ImageHost | ImageSource
) -> ProcessingContext:
    context = ProcessingContext()
    context.shared_data.uploaded_images[tracker] = _uploaded()
    context.shared_data.uploaded_image_hosts[tracker] = host
    return context


# --------------------------------------------------------------------------
# image reuse
# --------------------------------------------------------------------------
def test_images_are_reused_when_the_destination_is_unchanged() -> None:
    context = _context_with_upload(TrackerSelection.AITHER, ImageHost.CHEVERETO_V3)

    reusable = ProcessBackEnd._reusable_uploaded_images(
        context, TrackerSelection.AITHER, ImageHost.CHEVERETO_V3
    )

    assert reusable == _uploaded()


def test_images_are_not_reused_after_the_image_host_changes() -> None:
    """The stored URLs point at a host this tracker no longer uploads to."""
    context = _context_with_upload(TrackerSelection.AITHER, ImageHost.CHEVERETO_V3)

    reusable = ProcessBackEnd._reusable_uploaded_images(
        context, TrackerSelection.AITHER, ImageHost.PIXHOST
    )

    assert reusable is None


def test_a_tracker_without_recorded_uploads_gets_none() -> None:
    context = _context_with_upload(TrackerSelection.AITHER, ImageHost.CHEVERETO_V3)

    reusable = ProcessBackEnd._reusable_uploaded_images(
        context, TrackerSelection.HUNO, ImageHost.CHEVERETO_V3
    )

    assert reusable is None


@pytest.mark.parametrize(
    "destination", [ImageHost.DISABLED, ImageSource.URLS, ImageSource.IMAGES]
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
    context = _context_with_upload(TrackerSelection.AITHER, ImageHost.CHEVERETO_V3)

    reusable = ProcessBackEnd._reusable_uploaded_images(
        context, TrackerSelection.AITHER, ImageHost.CHEVERETO_V3
    )
    assert reusable is not None
    reusable[99] = ImageUploadData(url="https://host/injected.png", medium_url=None)

    assert 99 not in context.shared_data.uploaded_images[TrackerSelection.AITHER]


# --------------------------------------------------------------------------
# "does this tracker still need the screenshot files on disk?"
# --------------------------------------------------------------------------
def test_a_tracker_with_reusable_urls_needs_no_local_files() -> None:
    context = _context_with_upload(TrackerSelection.AITHER, ImageHost.CHEVERETO_V3)

    assert not ProcessBackEnd.needs_local_images(
        context, TrackerSelection.AITHER, ImageHost.CHEVERETO_V3
    )


@pytest.mark.parametrize("destination", [ImageHost.DISABLED, ImageSource.URLS])
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
    context = _context_with_upload(TrackerSelection.AITHER, ImageHost.CHEVERETO_V3)

    assert ProcessBackEnd.needs_local_images(
        context, TrackerSelection.AITHER, ImageHost.PIXHOST
    )


def test_a_tracker_with_no_uploads_yet_needs_local_files() -> None:
    context = ProcessingContext()

    assert ProcessBackEnd.needs_local_images(
        context, TrackerSelection.AITHER, ImageHost.CHEVERETO_V3
    )


def test_empty_recorded_uploads_do_not_count_as_reusable() -> None:
    context = ProcessingContext()
    context.shared_data.uploaded_images[TrackerSelection.AITHER] = {}
    context.shared_data.uploaded_image_hosts[TrackerSelection.AITHER] = (
        ImageHost.CHEVERETO_V3
    )

    assert (
        ProcessBackEnd._reusable_uploaded_images(
            context, TrackerSelection.AITHER, ImageHost.CHEVERETO_V3
        )
        is None
    )


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
    source.shared_data.uploaded_image_hosts[TrackerSelection.AITHER] = (
        ImageHost.CHEVERETO_V3
    )
    source.shared_data.tracker_image_hosts[TrackerSelection.AITHER] = ImageUploadFromTo(
        ImageSource.IMAGES, ImageHost.CHEVERETO_V3
    )

    restored = ProcessingContext()
    context_from_dict(context_to_dict(source, {}), restored)

    assert restored.shared_data.uploaded_images == {
        TrackerSelection.AITHER: _uploaded()
    }
    assert restored.shared_data.uploaded_image_hosts == {
        TrackerSelection.AITHER: ImageHost.CHEVERETO_V3
    }
