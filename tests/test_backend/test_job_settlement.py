"""What the queue does to a job's files once it has run it.

A job that survives a successful upload unchanged is a job the next queue run
uploads again, so these are the tests that keep the queue from duplicating.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.backend import job_queue as job_queue_module
from src.backend.job_queue import (
    JobDisposition,
    JobQueueRunner,
    QueuedJobOutcome,
    QueuedJobResult,
)
from src.backend.jobs import (
    JobCodecError,
    JobStoreError,
    context_from_dict,
    context_to_dict,
    read_job_asset,
    store,
)
from src.backend.jobs.models import JobSummary
from src.backend.upload_retry import TrackerRunOutcome
from src.context.processing_context import ProcessingContext
from src.enums.image_host import ImageHost, ImageSource
from src.enums.tracker_selection import TrackerSelection
from src.packages.custom_types import ImageUploadData, ImageUploadFromTo

_TRACKERS = (TrackerSelection.AITHER, TrackerSelection.HUNO)
_NFOS = {TrackerSelection.AITHER: "a", TrackerSelection.HUNO: "h"}


@pytest.fixture
def working_dir(tmp_path: Path) -> Path:
    return tmp_path / "nfoforge"


def _job(working_dir: Path) -> tuple[Any, Path]:
    """A saved job covering two trackers, each with a stored NFO.

    Built by serializing a real context rather than by hand: `_settle` now
    re-serializes the live context back onto the job, so a document no
    `context_to_dict` could have produced would make every test here measure a
    round trip the application never performs.
    """
    source = ProcessingContext()
    source.shared_data.selected_trackers = list(_TRACKERS)
    for tracker, nfo in _NFOS.items():
        source.shared_data.tracker_release_data[tracker] = {
            "title": nfo,
            "nfo": nfo,
        }
    context = context_to_dict(
        source,
        {},
        {tracker: f"nfo/{tracker.name.lower()}.txt" for tracker in _TRACKERS},
    )

    job = store.build_job(
        "Two trackers",
        JobSummary(trackers=["Aither", "Huno"]),
        context,
    )
    directory = store.job_dir(working_dir, job.job_id, ensure_exists=True)
    nfo_dir = directory / store.JOB_NFO_DIR_NAME
    nfo_dir.mkdir(parents=True)
    for tracker, nfo in _NFOS.items():
        (nfo_dir / f"{tracker.name.lower()}.txt").write_text(nfo, encoding="utf-8")
    store.write_job_document(job, directory)
    return job, directory


def _context(directory: Path) -> ProcessingContext:
    """The live context a queued run would hold, restored the same way it is."""
    job = store.load_job(directory)
    context = ProcessingContext()
    context_from_dict(
        job.context, context, lambda name: read_job_asset(directory, name)
    )
    return context


def _runner(messages: list[str] | None = None) -> JobQueueRunner:
    """A runner whose queue-log lines land in `messages`, when given one.

    Nothing in the original ten tests cares what gets logged, only what
    happens to the job's files -- which is exactly how a message emitted by
    `_settle` could vanish without a single test failing.
    """
    return JobQueueRunner(
        backend=SimpleNamespace(),
        config=SimpleNamespace(),
        text_update=messages.append if messages is not None else None,
    )


def test_a_job_whose_trackers_all_uploaded_is_deleted(working_dir: Path) -> None:
    job, directory = _job(working_dir)
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.UPLOADED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOADED,
        },
    )

    _runner()._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.DELETED
    assert not directory.exists()


def test_a_fully_uploaded_archive_is_retained_with_history(
    working_dir: Path,
) -> None:
    job, directory = _job(working_dir)
    job.archived = True
    store.write_job_document(job, directory)
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.UPLOADED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED,
            TrackerSelection.HUNO: TrackerRunOutcome.INJECTION_FAILED,
        },
    )

    _runner()._settle(job, outcome, _context(directory))

    reloaded = store.load_job(directory)
    assert directory.exists()
    assert reloaded.archived
    assert reloaded.summary.trackers == []
    assert set(reloaded.uploaded_trackers) == {"AITHER", "HUNO"}
    assert outcome.disposition is JobDisposition.NARROWED


def test_a_partly_uploaded_job_is_narrowed_to_what_is_left(working_dir: Path) -> None:
    """HUNO uploads and is dropped; AITHER failed and is retained.

    Retaining AITHER rather than HUNO matters: TrackerSelection.AITHER's name
    ("AITHER") and value ("Aither") differ, while HUNO's are both "HUNO". A
    test that retains HUNO passes whether the narrowing keys on .name, .value
    or str() -- it would not catch the wrong one. Retaining AITHER pins it.
    """
    job, directory = _job(working_dir)
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.UPLOADED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOAD_FAILED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOADED,
        },
    )

    _runner()._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.NARROWED
    reloaded = store.load_job(directory)
    shared = reloaded.context["shared_data"]
    assert set(shared["tracker_release_data"]) == {"AITHER"}
    assert shared["selected_trackers"] == ["AITHER"]
    assert reloaded.summary.trackers == ["Aither"]
    # the uploaded tracker's NFO must not linger and imply the job still covers it
    assert {p.name for p in (directory / store.JOB_NFO_DIR_NAME).iterdir()} == {
        "aither.txt"
    }


def test_a_job_that_uploaded_nothing_is_left_alone(working_dir: Path) -> None:
    job, directory = _job(working_dir)
    before = (directory / store.JOB_DOCUMENT_NAME).read_text(encoding="utf-8")
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.FAILED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOAD_FAILED,
            TrackerSelection.HUNO: TrackerRunOutcome.NOT_ATTEMPTED,
        },
    )

    _runner()._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.KEPT
    assert (directory / store.JOB_DOCUMENT_NAME).read_text(encoding="utf-8") == before


def test_an_unknown_outcome_never_deletes_the_job(working_dir: Path) -> None:
    """`MAY_HAVE_UPLOADED` means nobody can say. Deleting would destroy the evidence."""
    job, directory = _job(working_dir)
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.FAILED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.MAY_HAVE_UPLOADED,
            TrackerSelection.HUNO: TrackerRunOutcome.MAY_HAVE_UPLOADED,
        },
    )

    _runner()._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.KEPT
    assert directory.exists()


def test_upload_disabled_alone_never_deletes_the_job(working_dir: Path) -> None:
    """Uploads switched off in config is a dry run, not a finished job."""
    job, directory = _job(working_dir)
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.UPLOADED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOAD_DISABLED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOAD_DISABLED,
        },
    )

    _runner()._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.KEPT
    assert directory.exists()


def test_an_uploaded_tracker_alongside_an_unknown_one_is_narrowed_not_deleted(
    working_dir: Path,
) -> None:
    """`MAY_HAVE_UPLOADED` is neither retryable nor done, so mixed with a
    provable upload the job must be narrowed to the unknown tracker, not
    deleted -- deleting would destroy the only record of it."""
    job, directory = _job(working_dir)
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.UPLOADED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.MAY_HAVE_UPLOADED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOADED,
        },
    )

    _runner()._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.NARROWED
    reloaded = store.load_job(directory)
    shared = reloaded.context["shared_data"]
    assert set(shared["tracker_release_data"]) == {"AITHER"}
    assert shared["selected_trackers"] == ["AITHER"]
    assert reloaded.summary.trackers == ["Aither"]
    assert {p.name for p in (directory / store.JOB_NFO_DIR_NAME).iterdir()} == {
        "aither.txt"
    }


def test_an_uploaded_tracker_alongside_a_disabled_one_is_narrowed_not_deleted(
    working_dir: Path,
) -> None:
    """A disabled tracker never uploaded, so mixed with a provable upload the
    job must be narrowed to the disabled tracker, not deleted -- deleting
    would throw away its prepared torrent and NFO before it ever ran."""
    job, directory = _job(working_dir)
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.UPLOADED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOAD_DISABLED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOADED,
        },
    )

    _runner()._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.NARROWED
    reloaded = store.load_job(directory)
    shared = reloaded.context["shared_data"]
    assert set(shared["tracker_release_data"]) == {"AITHER"}
    assert shared["selected_trackers"] == ["AITHER"]
    assert reloaded.summary.trackers == ["Aither"]
    assert {p.name for p in (directory / store.JOB_NFO_DIR_NAME).iterdir()} == {
        "aither.txt"
    }


def test_a_failed_tracker_alongside_an_unknown_one_is_left_untouched(
    working_dir: Path,
) -> None:
    """Nothing provably landed, so the job is exactly itself -- narrowing here
    would drop the unknown tracker's NFO while nothing was actually confirmed
    uploaded anywhere."""
    job, directory = _job(working_dir)
    before = (directory / store.JOB_DOCUMENT_NAME).read_text(encoding="utf-8")
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.FAILED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOAD_FAILED,
            TrackerSelection.HUNO: TrackerRunOutcome.MAY_HAVE_UPLOADED,
        },
    )

    _runner()._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.KEPT
    assert (directory / store.JOB_DOCUMENT_NAME).read_text(encoding="utf-8") == before
    assert {p.name for p in (directory / store.JOB_NFO_DIR_NAME).iterdir()} == {
        "aither.txt",
        "huno.txt",
    }


def test_a_failed_tracker_alongside_a_disabled_one_is_left_untouched(
    working_dir: Path,
) -> None:
    """Nothing provably landed here either, so the job is left exactly as it
    was rather than narrowed down to the disabled tracker."""
    job, directory = _job(working_dir)
    before = (directory / store.JOB_DOCUMENT_NAME).read_text(encoding="utf-8")
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.FAILED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOAD_FAILED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOAD_DISABLED,
        },
    )

    _runner()._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.KEPT
    assert (directory / store.JOB_DOCUMENT_NAME).read_text(encoding="utf-8") == before
    assert {p.name for p in (directory / store.JOB_NFO_DIR_NAME).iterdir()} == {
        "aither.txt",
        "huno.txt",
    }


def test_a_job_that_never_reached_upload_is_untouched(working_dir: Path) -> None:
    job, directory = _job(working_dir)
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.SKIPPED_DUPES,
        detail="possible duplicates on Aither",
    )

    _runner()._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.KEPT
    assert directory.exists()


# --------------------------------------------------------------------------
# what actually reaches the queue log -- the regression this file exists to
# catch is a message that silently stops being emitted
# --------------------------------------------------------------------------
def test_every_tracker_unconfirmed_is_named_in_the_log(working_dir: Path) -> None:
    """The one outcome nobody can retry or write off must say so, or the
    fully-unconfirmed run leaves no trace for a human to act on."""
    job, directory = _job(working_dir)
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.FAILED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.MAY_HAVE_UPLOADED,
            TrackerSelection.HUNO: TrackerRunOutcome.MAY_HAVE_UPLOADED,
        },
    )
    messages: list[str] = []

    _runner(messages)._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.KEPT
    assert directory.exists()
    logged = " ".join(messages)
    assert "Aither" in logged
    assert "HUNO" in logged


def test_every_tracker_disabled_emits_nothing(working_dir: Path) -> None:
    """Uploads switched off in config is the user's own choice, not a warning."""
    job, directory = _job(working_dir)
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.UPLOADED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOAD_DISABLED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOAD_DISABLED,
        },
    )
    messages: list[str] = []

    _runner(messages)._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.KEPT
    assert directory.exists()
    assert messages == []


def test_every_tracker_not_attempted_emits_nothing(working_dir: Path) -> None:
    """A run that never got as far as a tracker has nothing to report yet."""
    job, directory = _job(working_dir)
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.FAILED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.NOT_ATTEMPTED,
            TrackerSelection.HUNO: TrackerRunOutcome.NOT_ATTEMPTED,
        },
    )
    messages: list[str] = []

    _runner(messages)._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.KEPT
    assert directory.exists()
    assert messages == []


def test_a_narrowed_job_logs_both_the_kept_line_and_the_unconfirmed_warning(
    working_dir: Path,
) -> None:
    """Narrowing and the unconfirmed warning answer different questions, so a
    job that hits both must say both, not just the one that fired first."""
    job, directory = _job(working_dir)
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.UPLOADED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.MAY_HAVE_UPLOADED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOADED,
        },
    )
    messages: list[str] = []

    _runner(messages)._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.NARROWED
    assert any("Kept" in message for message in messages)
    assert any("Check" in message and "Aither" in message for message in messages)


# --------------------------------------------------------------------------
# what the run itself produced, not just which trackers it covers
# --------------------------------------------------------------------------
def test_urls_uploaded_during_the_run_are_written_back(working_dir: Path) -> None:
    """The queue used to re-narrow the document *as loaded from disk*.

    Everything the run produced -- above all the screenshots it had just
    uploaded -- was therefore thrown away, and the next queue run uploaded the
    same images to the same host all over again.
    """
    job, directory = _job(working_dir)
    context = _context(directory)
    context.shared_data.uploaded_images_by_host[ImageHost.PIXHOST] = {
        0: ImageUploadData(url="https://pixhost/0.png", medium_url=None)
    }
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.UPLOADED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOAD_FAILED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOADED,
        },
    )

    _runner()._settle(job, outcome, context)

    reloaded = store.load_job(directory)
    assert reloaded.context["shared_data"]["uploaded_images_by_host"] == [
        {
            "name": "PIXHOST",
            "type": "ImageHost",
            "images": {"0": {"url": "https://pixhost/0.png", "medium_url": None}},
        }
    ]


def test_urls_are_written_back_even_when_every_tracker_failed(
    working_dir: Path,
) -> None:
    """Nothing landed, so the job still covers both trackers -- but the images
    it uploaded on the way are worth keeping, or the retry pays for them
    again."""
    job, directory = _job(working_dir)
    context = _context(directory)
    context.shared_data.uploaded_images_by_host[ImageHost.PIXHOST] = {
        0: ImageUploadData(url="https://pixhost/0.png", medium_url=None)
    }
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.FAILED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOAD_FAILED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOAD_FAILED,
        },
    )

    _runner()._settle(job, outcome, context)

    reloaded = store.load_job(directory)
    shared = reloaded.context["shared_data"]
    assert shared["uploaded_images_by_host"]
    # nothing landed, so both trackers are still the job's to upload
    assert set(shared["selected_trackers"]) == {"AITHER", "HUNO"}
    assert outcome.disposition is JobDisposition.KEPT


def test_an_uncertain_tracker_in_an_archive_keeps_its_prepared_work(
    working_dir: Path,
) -> None:
    """It must not run again, but "it never landed" has to be resolvable.

    Narrowing an uncertain tracker away left only its name, so answering "no,
    it is safe to upload" offered to restore a tracker whose title and NFO had
    already been deleted along with its sidecar.
    """
    job, directory = _job(working_dir)
    job.archived = True
    store.write_job_document(job, directory)
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.UPLOADED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.MAY_HAVE_UPLOADED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOADED,
        },
    )

    _runner()._settle(job, outcome, _context(directory))

    reloaded = store.load_job(directory)
    shared = reloaded.context["shared_data"]
    assert reloaded.uncertain_trackers == ["AITHER"]
    # kept out of the run...
    assert shared["selected_trackers"] == []
    # ...but everything needed to put it back is still here
    assert shared["tracker_release_data"]["AITHER"]["title"] == "a"
    assert (directory / store.JOB_NFO_DIR_NAME / "aither.txt").is_file()


def test_an_uncertain_tracker_in_an_archive_keeps_its_image_host(
    working_dir: Path,
) -> None:
    """The destination its screenshots were bound for is part of that work.

    `tracker_image_hosts` is re-serialized from the run that just happened, so
    a tracker held back from it lost its entry while keeping everything else.
    Resolving it later then re-derived the host from the global last-used
    preference instead of the one this job chose, which can point at a host
    whose stored URLs the run cannot reuse.
    """
    job, directory = _job(working_dir)
    job.archived = True
    store.write_job_document(job, directory)
    context = _context(directory)
    context.shared_data.tracker_image_hosts[TrackerSelection.AITHER] = (
        ImageUploadFromTo(ImageSource.IMAGES, ImageHost.PIXHOST)
    )
    context.shared_data.tracker_image_hosts[TrackerSelection.HUNO] = ImageUploadFromTo(
        ImageSource.IMAGES, ImageHost.CHEVERETO_V3
    )
    store.write_job_document(
        store.build_job(
            job.name,
            job.summary,
            context_to_dict(context, {}, {}),
            archived=True,
        ),
        directory,
    )
    job = store.load_job(directory)
    job.archived = True

    # the run that follows only covers HUNO, so AITHER never gets a row
    run_context = _context(directory)
    run_context.shared_data.tracker_image_hosts.pop(TrackerSelection.AITHER)
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.UPLOADED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.MAY_HAVE_UPLOADED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOADED,
        },
    )

    _runner()._settle(job, outcome, run_context)

    shared = store.load_job(directory).context["shared_data"]
    assert shared["selected_trackers"] == []
    assert list(shared["tracker_image_hosts"]) == ["AITHER"]


def test_a_rebuild_that_fails_leaves_the_job_exactly_as_it_was(
    working_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-serializing is a bonus, not a precondition: failing it must not cost
    the job the state it already had on disk."""
    job, directory = _job(working_dir)
    before = (directory / store.JOB_DOCUMENT_NAME).read_text(encoding="utf-8")

    def _boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise JobCodecError("could not serialize")

    monkeypatch.setattr(job_queue_module, "rebuild_job_document", _boom)
    messages: list[str] = []
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.FAILED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOAD_FAILED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOAD_FAILED,
        },
    )

    _runner(messages)._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.KEPT
    assert (directory / store.JOB_DOCUMENT_NAME).read_text(encoding="utf-8") == before
    assert any("could not be written back" in message for message in messages)


def test_a_failed_delete_is_reported_not_just_logged(
    working_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A delete that fails leaves a fully-uploaded job on disk -- exactly the
    state that re-uploads everywhere next run, so it cannot be silent."""
    job, directory = _job(working_dir)

    def _boom(_directory: Path) -> None:
        raise JobStoreError("disk is read-only")

    monkeypatch.setattr(job_queue_module, "delete_job", _boom)
    messages: list[str] = []
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.UPLOADED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOADED,
        },
    )

    _runner(messages)._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.KEPT
    assert directory.exists()
    assert any("could not be removed" in message for message in messages)


def test_a_failed_narrow_is_reported_not_just_logged(
    working_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A narrow that fails to write leaves the uploaded trackers still listed
    -- exactly the state that re-uploads them next run -- so it too must
    reach the queue log, not just the application log."""
    job, directory = _job(working_dir)

    def _boom(*_args: Any, **_kwargs: Any) -> Path:
        raise JobStoreError("disk is read-only")

    monkeypatch.setattr(job_queue_module, "write_job_document", _boom)
    messages: list[str] = []
    outcome = QueuedJobOutcome(
        job_name=job.name,
        path=directory,
        result=QueuedJobResult.UPLOADED,
        outcomes={
            TrackerSelection.AITHER: TrackerRunOutcome.UPLOADED,
            TrackerSelection.HUNO: TrackerRunOutcome.UPLOAD_FAILED,
        },
    )

    _runner(messages)._settle(job, outcome, _context(directory))

    assert outcome.disposition is JobDisposition.KEPT
    assert any(
        "already uploaded and will send to them again" in message
        for message in messages
    )
