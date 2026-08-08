"""Coverage for running prepared jobs back to back.

The policies under test are the ones that make unattended running safe: never
upload over a possible duplicate, never block on a prompt, and never let one bad
job stop the rest.
"""

from pathlib import Path
import struct
from types import SimpleNamespace
from typing import Any, cast
import wave

from pymediainfo import MediaInfo
import pytest

from src.backend.job_queue import DupeCheckResult, JobQueueRunner, QueuedJobResult
from src.backend.jobs import store
from src.backend.jobs.models import JobSummary
from src.backend.process import ProcessBackEnd
from src.backend.upload_retry import TrackerRunOutcome
from src.context.processing_context import ProcessingContext
from src.enums.image_host import ImageHost, ImageSource
from src.enums.tracker_selection import TrackerSelection
from src.packages.custom_types import ImageUploadData, ImageUploadFromTo


@pytest.fixture
def working_dir(tmp_path: Path) -> Path:
    return tmp_path / "nfoforge"


@pytest.fixture
def media(tmp_path: Path) -> Path:
    """A real file libmediainfo can parse, so restore validation is exercised."""
    path = tmp_path / "Release.2024.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(struct.pack("<" + "h" * 800, *([0] * 800)))
    return path


def _config() -> Any:
    return SimpleNamespace(
        settings=SimpleNamespace(
            templates=SimpleNamespace(
                trim_blocks=True,
                lstrip_blocks=False,
                newline_sequence="\r\n",
                keep_trailing_newline=True,
            ),
            general=SimpleNamespace(enable_plugins=False),
        ),
        plugin_manager=_PluginManager(),
    )


class _PluginManager:
    def jinja2_filters(self, enabled: bool) -> dict:
        return {}

    def jinja2_functions(self, enabled: bool) -> dict:
        return {}

    def flat_filters(self, enabled: bool) -> dict:
        return {}

    def custom_edition_info(self, enabled: bool) -> tuple:
        return ()

    def custom_cut_names(self, enabled: bool) -> frozenset:
        return frozenset()


def _save(
    working_dir: Path,
    media: Path,
    name: str,
    *,
    prepared: bool = True,
    destination: ImageHost | ImageSource = ImageHost.CHEVERETO_V3,
    uploaded_to: ImageHost | ImageSource | None = ImageHost.CHEVERETO_V3,
    loaded_images: list[Path] | None = None,
) -> Path:
    """Write a job whose context restores cleanly.

    `uploaded_to` is the host its images already went to (None for a job that
    still has to upload them), which together with `destination` is what
    decides whether local screenshot files are still needed.
    """
    from src.backend.jobs.codec import context_to_dict

    context = ProcessingContext()
    context.media_input.input_path = media
    context.media_input.working_dir = media.parent / "work"
    context.media_input.file_list.append(media)
    context.media_input.file_list_mediainfo[media] = MediaInfo.parse(  # type: ignore[reportArgumentType]
        media, legacy_stream_display=True
    )
    context.shared_data.selected_trackers = [TrackerSelection.AITHER]
    context.shared_data.tracker_image_hosts[TrackerSelection.AITHER] = (
        ImageUploadFromTo(ImageSource.IMAGES, destination)
    )
    if loaded_images is not None:
        context.shared_data.loaded_images = loaded_images
    if uploaded_to is not None:
        context.shared_data.uploaded_images[TrackerSelection.AITHER] = {
            0: ImageUploadData(url="https://host/a.png", medium_url=None)
        }
        context.shared_data.uploaded_image_hosts[TrackerSelection.AITHER] = uploaded_to
    if prepared:
        context.shared_data.tracker_release_data[TrackerSelection.AITHER] = {
            "title": "Release 2024",
            "nfo": "body",
        }

    # None (rather than {}) inlines the MediaInfo dumps, so the saved job
    # restores without needing sidecar files written alongside it
    document = context_to_dict(context, None)
    job = store.build_job(name, JobSummary(title=name), document, "config")
    return store.save_job(job, working_dir)


def _runner(
    backend: Any,
    monkeypatch: pytest.MonkeyPatch,
    dupes: list[str] | None = None,
) -> JobQueueRunner:
    runner = JobQueueRunner(cast(ProcessBackEnd, backend), _config())
    monkeypatch.setattr(
        runner, "_check_dupes", lambda *_a, **_k: DupeCheckResult(found=dupes or [])
    )
    return runner


def _async_returning(results: dict) -> Any:
    """A stand-in for `dupe_checks`, which the runner awaits."""

    async def _dupe_checks(**_kwargs: Any) -> dict:
        return results

    return _dupe_checks


class _Backend:
    """Records the jobs it was asked to upload."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.uploaded: list[str] = []
        self.fail_on = fail_on
        self.callbacks: list[dict] = []

    def process_trackers(self, **kwargs: Any) -> None:
        self.callbacks.append(kwargs)
        title = kwargs["context"].shared_data.tracker_release_data.get(
            TrackerSelection.AITHER, {}
        )
        self.uploaded.append(str(title.get("title")))
        record = kwargs.get("run_outcome_cb")
        if self.fail_on and self.fail_on in self.uploaded[-1]:
            if record:
                record(TrackerSelection.AITHER, TrackerRunOutcome.UPLOAD_FAILED)
            raise RuntimeError("tracker unreachable")
        if record:
            record(TrackerSelection.AITHER, TrackerRunOutcome.UPLOADED)


# --------------------------------------------------------------------------
# ordering and isolation
# --------------------------------------------------------------------------
def test_jobs_run_in_the_order_given(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _save(working_dir, media, "first")
    second = _save(working_dir, media, "second")
    backend = _Backend()

    results = _runner(backend, monkeypatch).run([first, second])

    assert [r.result for r in results] == [
        QueuedJobResult.UPLOADED,
        QueuedJobResult.UPLOADED,
    ]
    assert len(backend.uploaded) == 2


def test_one_failing_job_does_not_stop_the_rest(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A flaky tracker must cost that job and nothing behind it."""
    first = _save(working_dir, media, "first")
    second = _save(working_dir, media, "second")
    backend = _Backend(fail_on="Release 2024")

    results = _runner(backend, monkeypatch).run([first, second])

    assert len(results) == 2
    assert results[0].result is QueuedJobResult.FAILED
    assert results[1].result is QueuedJobResult.FAILED
    assert len(backend.uploaded) == 2


def test_a_failed_job_reports_what_can_be_retried(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever never reached a tracker is handed back to be saved again."""
    path = _save(working_dir, media, "first")
    backend = _Backend(fail_on="Release 2024")

    results = _runner(backend, monkeypatch).run([path])

    assert results[0].deferrable_trackers() == {TrackerSelection.AITHER}


def test_an_unreadable_job_is_skipped_not_fatal(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = _save(working_dir, media, "good")
    broken = store.jobs_dir(working_dir) / "broken"
    broken.mkdir(parents=True)
    (broken / store.JOB_DOCUMENT_NAME).write_text("{not json", encoding="utf-8")
    backend = _Backend()

    results = _runner(backend, monkeypatch).run([broken, good])

    assert results[0].result is QueuedJobResult.SKIPPED_UNUSABLE
    assert results[1].result is QueuedJobResult.UPLOADED


# --------------------------------------------------------------------------
# the safety policies
# --------------------------------------------------------------------------
def test_a_job_with_possible_dupes_is_skipped(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing is uploaded over a possible duplicate without a human."""
    path = _save(working_dir, media, "dupe")
    backend = _Backend()

    results = _runner(backend, monkeypatch, dupes=["Aither"]).run([path])

    assert results[0].result is QueuedJobResult.SKIPPED_DUPES
    assert "Aither" in results[0].detail
    assert backend.uploaded == []


def test_a_skipped_dupe_job_still_lets_the_next_run(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _save(working_dir, media, "dupe")
    second = _save(working_dir, media, "clean")
    backend = _Backend()
    runner = JobQueueRunner(cast(ProcessBackEnd, backend), _config())
    calls = {"n": 0}

    def dupes(*_a: Any, **_k: Any) -> DupeCheckResult:
        calls["n"] += 1
        return DupeCheckResult(found=["Aither"] if calls["n"] == 1 else [])

    monkeypatch.setattr(runner, "_check_dupes", dupes)

    results = runner.run([first, second])

    assert results[0].result is QueuedJobResult.SKIPPED_DUPES
    assert results[1].result is QueuedJobResult.UPLOADED


def test_a_job_whose_check_could_not_run_is_skipped(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unverified is not the same as clean.

    The interactive flow already stops and asks when a dupe check fails; the
    queue has nobody to ask, so it must not be the one path that uploads a
    release nothing actually cleared.
    """
    path = _save(working_dir, media, "unverified")
    backend = _Backend()
    runner = JobQueueRunner(cast(ProcessBackEnd, backend), _config())
    monkeypatch.setattr(
        runner,
        "_check_dupes",
        lambda *_a, **_k: DupeCheckResult(unverified=["Aither"]),
    )

    results = runner.run([path])

    assert results[0].result is QueuedJobResult.SKIPPED_UNVERIFIED
    assert "could not check" in results[0].detail
    assert backend.uploaded == []


def test_found_and_unverified_are_reported_apart(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Already there" and "nobody could tell" call for different responses."""
    path = _save(working_dir, media, "both")
    backend = _Backend()
    runner = JobQueueRunner(cast(ProcessBackEnd, backend), _config())
    monkeypatch.setattr(
        runner,
        "_check_dupes",
        lambda *_a, **_k: DupeCheckResult(found=["Aither"], unverified=["HUNO"]),
    )

    results = runner.run([path])

    # a real duplicate outranks an unverified one in the label
    assert results[0].result is QueuedJobResult.SKIPPED_DUPES
    assert "possible duplicates on Aither" in results[0].detail
    assert "could not check HUNO" in results[0].detail


@pytest.mark.parametrize(
    ("found", "unverified", "blocks"),
    [
        ([], [], False),
        (["Aither"], [], True),
        ([], ["Aither"], True),
        (["Aither"], ["HUNO"], True),
    ],
)
def test_what_blocks_an_unattended_upload(
    found: list[str], unverified: list[str], blocks: bool
) -> None:
    assert DupeCheckResult(found, unverified).blocks_upload() is blocks


def test_a_failing_tracker_check_is_classified_unverified(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercises the real classifier, not a stubbed result."""
    backend = SimpleNamespace(
        dupe_checks=_async_returning(
            {
                TrackerSelection.AITHER: (
                    TrackerSelection.AITHER,
                    False,
                    "search is down",
                )
            }
        )
    )
    runner = JobQueueRunner(cast(ProcessBackEnd, backend), _config())

    result = runner._check_dupes(ProcessingContext(), {"Aither": {}})

    assert result.unverified == ["Aither"]
    assert result.found == []


def test_a_tracker_the_check_never_reported_on_is_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silence must not be read as a clean result."""
    backend = SimpleNamespace(dupe_checks=_async_returning({}))
    runner = JobQueueRunner(cast(ProcessBackEnd, backend), _config())

    result = runner._check_dupes(ProcessingContext(), {"Aither": {}, "HUNO": {}})

    assert sorted(result.unverified) == ["Aither", "HUNO"]


def test_a_check_that_crashes_leaves_everything_unverified() -> None:
    async def boom(**_kwargs: Any) -> dict:
        raise RuntimeError("network gone")

    backend = SimpleNamespace(dupe_checks=boom)
    runner = JobQueueRunner(cast(ProcessBackEnd, backend), _config())

    result = runner._check_dupes(ProcessingContext(), {"Aither": {}})

    assert result.unverified == ["Aither"]
    assert result.blocks_upload()


def test_a_clean_check_does_not_block() -> None:
    backend = SimpleNamespace(
        dupe_checks=_async_returning(
            {TrackerSelection.AITHER: (TrackerSelection.AITHER, True, [])}
        )
    )
    runner = JobQueueRunner(cast(ProcessBackEnd, backend), _config())

    result = runner._check_dupes(ProcessingContext(), {"Aither": {}})

    assert not result.blocks_upload()


def test_an_unprepared_job_is_refused_rather_than_blocking(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It would stop at a prompt the queue has nobody to answer."""
    path = _save(working_dir, media, "raw", prepared=False)
    backend = _Backend()

    results = _runner(backend, monkeypatch).run([path])

    assert results[0].result is QueuedJobResult.SKIPPED_NOT_PREPARED
    assert backend.uploaded == []


def test_missing_screenshots_do_not_block_a_job_that_needs_none(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its images already went to this host, so the local files are irrelevant."""
    path = _save(
        working_dir,
        media,
        "uploaded",
        uploaded_to=ImageHost.CHEVERETO_V3,
        loaded_images=[media.parent / "never-existed.png"],
    )
    backend = _Backend()

    results = _runner(backend, monkeypatch).run([path])

    assert results[0].result is QueuedJobResult.UPLOADED


def test_missing_screenshots_block_a_job_that_still_has_to_upload_them(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _save(
        working_dir,
        media,
        "needs-images",
        uploaded_to=None,
        loaded_images=[media.parent / "never-existed.png"],
    )
    backend = _Backend()

    results = _runner(backend, monkeypatch).run([path])

    assert results[0].result is QueuedJobResult.SKIPPED_UNUSABLE
    assert "screenshot" in results[0].detail


def test_a_changed_image_host_makes_missing_screenshots_matter_again(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recorded URLs belong to a host this tracker no longer uploads to,
    so the run falls back to the local files -- which are gone."""
    path = _save(
        working_dir,
        media,
        "moved-host",
        uploaded_to=ImageHost.PIXHOST,
        destination=ImageHost.CHEVERETO_V3,
        loaded_images=[media.parent / "never-existed.png"],
    )
    backend = _Backend()

    results = _runner(backend, monkeypatch).run([path])

    assert results[0].result is QueuedJobResult.SKIPPED_UNUSABLE
    assert backend.uploaded == []


def test_a_disabled_tracker_never_makes_screenshots_required(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Disabled tracker has no recorded uploads but sends no images either."""
    path = _save(
        working_dir,
        media,
        "disabled",
        uploaded_to=None,
        destination=ImageHost.DISABLED,
        loaded_images=[media.parent / "never-existed.png"],
    )
    backend = _Backend()

    results = _runner(backend, monkeypatch).run([path])

    assert results[0].result is QueuedJobResult.UPLOADED


def test_a_job_whose_media_vanished_is_skipped(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _save(working_dir, media, "gone")
    media.unlink()
    backend = _Backend()

    results = _runner(backend, monkeypatch).run([path])

    assert results[0].result is QueuedJobResult.SKIPPED_UNUSABLE
    assert backend.uploaded == []


def test_the_queue_never_passes_a_prompt_callback(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retry callback being None is what makes failures non-blocking."""
    path = _save(working_dir, media, "quiet")
    backend = _Backend()

    _runner(backend, monkeypatch).run([path])

    kwargs = backend.callbacks[0]
    assert kwargs["token_prompt_cb"] is None
    assert kwargs["overview_cb"] is None
    assert kwargs["upload_retry_cb"] is None


def test_cancelling_stops_before_the_next_job(
    working_dir: Path, media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _save(working_dir, media, "first")
    second = _save(working_dir, media, "second")
    backend = _Backend()
    runner = JobQueueRunner(
        cast(ProcessBackEnd, backend),
        _config(),
        is_cancelled=lambda: len(backend.uploaded) >= 1,
    )
    monkeypatch.setattr(runner, "_check_dupes", lambda *_a, **_k: DupeCheckResult())

    results = runner.run([first, second])

    assert len(results) == 1
    assert len(backend.uploaded) == 1
