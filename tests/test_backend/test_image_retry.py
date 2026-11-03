"""Coverage for what happens when images do not reach their host.

A host dropping three images out of twelve used to end the run outright, and
the failures were written down as if they were URLs -- so the obvious next
move, running the job again, published three blank images. These guard the way
out of that: retry only the gaps, give the attempt more room, or send the whole
set somewhere else.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from nfoforge.backend.process import ProcessBackEnd
from nfoforge.backend.upload_retry import (
    ImageRetryAction,
    ImageRetryDecision,
    ImageUploadFailure,
)
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.enums.image_host import ImageHost, ImageSource
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.exceptions import ImageUploadError, ProcessCancelled
from nfoforge.packages.custom_types import (
    ImageHostRef,
    ImageUploadData,
    ImageUploadFromTo,
)

PIXHOST = ImageHostRef(ImageHost.PIXHOST)
LENSDUMP = ImageHostRef(ImageHost.LENSDUMP)

TOTAL = 12
FAILED_POSITIONS = (3, 6, 11)


class _Upload:
    """A scripted stand-in for `handle_image_upload`, recording each call."""

    def __init__(self, *, fail: dict[ImageHostRef, set[int]] | None = None) -> None:
        self.fail = fail or {}
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        pending: dict[ImageHostRef, tuple[int, ...]],
        filepaths: list[Path],
        _progress_bar_cb: Any,
        timeouts: dict[ImageHostRef, int] | None = None,
    ) -> dict[ImageHostRef, dict[int, ImageUploadData]]:
        self.calls.append(
            {
                "pending": {host: tuple(p) for host, p in pending.items()},
                "files": list(filepaths),
                "timeouts": dict(timeouts or {}),
            }
        )
        results: dict[ImageHostRef, dict[int, ImageUploadData]] = {}
        for host, positions in pending.items():
            doomed = self.fail.get(host, set())
            results[host] = {
                position: (
                    ImageUploadData(None, None)
                    if position in doomed
                    else ImageUploadData(
                        f"https://{host.kind.name}/{position}.png", None
                    )
                )
                for position in positions
            }
        # a host only fails a position once; a retry of it succeeds
        self.fail = {}
        return results


def _backend(upload: _Upload) -> ProcessBackEnd:
    backend = object.__new__(ProcessBackEnd)
    backend.config = cast(
        Any,
        SimpleNamespace(
            settings=SimpleNamespace(
                general=SimpleNamespace(timeout=60),
                screenshots=SimpleNamespace(
                    optimize_generated_images=False,
                    optimize_downloaded_images=False,
                ),
            )
        ),
    )
    backend.handle_image_upload = upload  # pyright: ignore[reportAttributeAccessIssue]
    return cast(ProcessBackEnd, backend)


def _context(
    tmp_path: Path, *trackers: tuple[TrackerSelection, ImageHostRef]
) -> ProcessingContext:
    context = ProcessingContext()
    context.shared_data.loaded_images = [
        tmp_path / f"shot_{index:02d}.png" for index in range(TOTAL)
    ]
    for tracker, host in trackers:
        context.shared_data.tracker_image_hosts[tracker] = ImageUploadFromTo(
            ImageSource.IMAGES, host
        )
    return context


def _process_dict(*trackers: tuple[TrackerSelection, ImageHostRef]) -> dict[str, Any]:
    return {
        tracker.value: {"image_host_data": ImageUploadFromTo(ImageSource.IMAGES, host)}
        for tracker, host in trackers
    }


def _run(
    backend: ProcessBackEnd,
    context: ProcessingContext,
    trackers: tuple[tuple[TrackerSelection, ImageHostRef], ...],
    image_retry_cb: Any = None,
) -> dict[TrackerSelection, dict[int, ImageUploadData]]:
    return backend.handle_images_for_trackers(
        context=context,
        process_dict=_process_dict(*trackers),
        queued_text_update=lambda _text: None,
        progress_bar_cb=lambda _value: None,
        image_retry_cb=image_retry_cb,
    )


# --------------------------------------------------------------------------
# retrying the gaps
# --------------------------------------------------------------------------
def test_a_retry_sends_only_the_positions_that_failed(tmp_path: Path) -> None:
    """The whole point: three images, not twelve."""
    upload = _Upload(fail={PIXHOST: set(FAILED_POSITIONS)})
    trackers = ((TrackerSelection.AITHER, PIXHOST),)
    context = _context(tmp_path, *trackers)

    result = _run(
        _backend(upload),
        context,
        trackers,
        lambda _failure: ImageRetryDecision(action=ImageRetryAction.RETRY),
    )

    assert len(upload.calls) == 2
    assert upload.calls[0]["pending"] == {PIXHOST: tuple(range(TOTAL))}
    assert upload.calls[1]["pending"] == {PIXHOST: FAILED_POSITIONS}
    # every position ends up holding its own URL
    images = result[TrackerSelection.AITHER]
    assert len(images) == TOTAL
    assert all(images[index].url for index in range(TOTAL))
    assert images[6].url == "https://PIXHOST/6.png"


def test_the_failure_names_the_positions_and_the_trackers_waiting(
    tmp_path: Path,
) -> None:
    seen: list[ImageUploadFailure] = []
    upload = _Upload(fail={PIXHOST: set(FAILED_POSITIONS)})
    trackers = (
        (TrackerSelection.AITHER, PIXHOST),
        (TrackerSelection.HUNO, PIXHOST),
    )
    context = _context(tmp_path, *trackers)

    def retry(failure: ImageUploadFailure) -> ImageRetryDecision:
        seen.append(failure)
        return ImageRetryDecision(action=ImageRetryAction.RETRY)

    _run(_backend(upload), context, trackers, retry)

    (failure,) = seen
    assert failure.host == PIXHOST
    assert failure.failed_positions == FAILED_POSITIONS
    assert failure.total == TOTAL
    assert set(failure.trackers) == {TrackerSelection.AITHER, TrackerSelection.HUNO}
    assert failure.timeout == 60
    assert "3 of 12" in failure.message


def test_a_retry_can_give_the_attempt_more_room(tmp_path: Path) -> None:
    """The configured timeout is what just failed, so it must be raisable."""
    upload = _Upload(fail={PIXHOST: set(FAILED_POSITIONS)})
    trackers = ((TrackerSelection.AITHER, PIXHOST),)
    context = _context(tmp_path, *trackers)

    _run(
        _backend(upload),
        context,
        trackers,
        lambda _failure: ImageRetryDecision(action=ImageRetryAction.RETRY, timeout=180),
    )

    assert upload.calls[0]["timeouts"] == {}
    assert upload.calls[1]["timeouts"] == {PIXHOST: 180}


# --------------------------------------------------------------------------
# switching hosts
# --------------------------------------------------------------------------
def test_switching_hosts_resends_every_image_and_moves_every_tracker(
    tmp_path: Path,
) -> None:
    """A tracker cannot take nine images from one host and three from another."""
    upload = _Upload(fail={PIXHOST: set(FAILED_POSITIONS)})
    trackers = (
        (TrackerSelection.AITHER, PIXHOST),
        (TrackerSelection.HUNO, PIXHOST),
    )
    context = _context(tmp_path, *trackers)

    result = _run(
        _backend(upload),
        context,
        trackers,
        lambda _failure: ImageRetryDecision(
            action=ImageRetryAction.SWITCH_HOST, host=LENSDUMP
        ),
    )

    assert upload.calls[1]["pending"] == {LENSDUMP: tuple(range(TOTAL))}
    for tracker in (TrackerSelection.AITHER, TrackerSelection.HUNO):
        assert result[tracker][0].url == "https://LENSDUMP/0.png"
        # what a job saved after this point would remember
        assert context.shared_data.uploaded_image_hosts[tracker] == LENSDUMP
        assert context.shared_data.tracker_image_hosts[tracker] == ImageUploadFromTo(
            ImageSource.IMAGES, LENSDUMP
        )


def test_the_abandoned_hosts_successful_uploads_are_still_recorded(
    tmp_path: Path,
) -> None:
    """Those nine URLs are real: the host has the images whatever happens next."""
    upload = _Upload(fail={PIXHOST: set(FAILED_POSITIONS)})
    trackers = ((TrackerSelection.AITHER, PIXHOST),)
    context = _context(tmp_path, *trackers)

    _run(
        _backend(upload),
        context,
        trackers,
        lambda _failure: ImageRetryDecision(
            action=ImageRetryAction.SWITCH_HOST, host=LENSDUMP
        ),
    )

    kept = context.shared_data.uploaded_images_by_host[PIXHOST]
    assert set(kept) == set(range(TOTAL)) - set(FAILED_POSITIONS)


# --------------------------------------------------------------------------
# cancelling, and the headless contract
# --------------------------------------------------------------------------
def test_cancelling_ends_the_run_as_cancelled_not_as_a_crash(tmp_path: Path) -> None:
    upload = _Upload(fail={PIXHOST: set(FAILED_POSITIONS)})
    trackers = ((TrackerSelection.AITHER, PIXHOST),)
    context = _context(tmp_path, *trackers)

    with pytest.raises(ProcessCancelled):
        _run(
            _backend(upload),
            context,
            trackers,
            lambda _failure: ImageRetryDecision(action=ImageRetryAction.CANCEL),
        )


def test_no_callback_still_fails_the_run_exactly_as_before(tmp_path: Path) -> None:
    """The job queue passes None: there is nobody to ask, so nothing is asked."""
    upload = _Upload(fail={PIXHOST: set(FAILED_POSITIONS)})
    trackers = ((TrackerSelection.AITHER, PIXHOST),)
    context = _context(tmp_path, *trackers)

    with pytest.raises(ImageUploadError) as excinfo:
        _run(_backend(upload), context, trackers, None)

    assert len(upload.calls) == 1
    assert "3 of 12" in str(excinfo.value)
    assert "3, 6, 11" in str(excinfo.value)


def test_a_failed_upload_is_never_recorded_as_reusable(tmp_path: Path) -> None:
    """The regression that started this.

    A URL-less entry recorded alongside the real ones was indistinguishable
    from them on the next run, which duly "reused" three blank images and
    published them to three trackers.
    """
    upload = _Upload(fail={PIXHOST: set(FAILED_POSITIONS)})
    trackers = ((TrackerSelection.AITHER, PIXHOST),)
    context = _context(tmp_path, *trackers)

    with pytest.raises(ImageUploadError):
        _run(_backend(upload), context, trackers, None)

    recorded = context.shared_data.uploaded_images_by_host[PIXHOST]
    assert set(recorded) == set(range(TOTAL)) - set(FAILED_POSITIONS)
    assert all(data.url for data in recorded.values())


# --------------------------------------------------------------------------
# topping up what a saved job already holds
# --------------------------------------------------------------------------
def test_a_partial_record_uploads_only_what_it_is_missing(tmp_path: Path) -> None:
    """The same primitive, reached from the other direction.

    A job saved mid-failure carries nine working URLs. Re-uploading all twelve
    would pay for them twice; trusting all twelve would be the original bug.
    """
    upload = _Upload()
    trackers = ((TrackerSelection.AITHER, PIXHOST),)
    context = _context(tmp_path, *trackers)
    context.shared_data.uploaded_images_by_host[PIXHOST] = {
        index: ImageUploadData(f"https://saved/{index}.png", None)
        for index in range(TOTAL)
        if index not in FAILED_POSITIONS
    }

    result = _run(_backend(upload), context, trackers)

    assert upload.calls[0]["pending"] == {PIXHOST: FAILED_POSITIONS}
    images = result[TrackerSelection.AITHER]
    assert images[0].url == "https://saved/0.png"
    assert images[3].url == "https://PIXHOST/3.png"


def test_a_complete_record_uploads_nothing_at_all(tmp_path: Path) -> None:
    upload = _Upload()
    trackers = ((TrackerSelection.AITHER, PIXHOST),)
    context = _context(tmp_path, *trackers)
    context.shared_data.uploaded_images_by_host[PIXHOST] = {
        index: ImageUploadData(f"https://saved/{index}.png", None)
        for index in range(TOTAL)
    }

    result = _run(_backend(upload), context, trackers)

    assert upload.calls == []
    assert len(result[TrackerSelection.AITHER]) == TOTAL
