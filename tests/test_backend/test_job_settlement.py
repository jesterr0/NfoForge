"""What the queue does to a job's files once it has run it.

A job that survives a successful upload unchanged is a job the next queue run
uploads again, so these are the tests that keep the queue from duplicating.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.backend.job_queue import (
    JobDisposition,
    JobQueueRunner,
    QueuedJobOutcome,
    QueuedJobResult,
)
from src.backend.jobs import store
from src.backend.jobs.models import JobSummary
from src.backend.upload_retry import TrackerRunOutcome
from src.enums.tracker_selection import TrackerSelection


@pytest.fixture
def working_dir(tmp_path: Path) -> Path:
    return tmp_path / "nfoforge"


def _job(working_dir: Path) -> tuple[Any, Path]:
    """A saved job covering two trackers, each with a stored NFO."""
    context = {
        "shared_data": {
            "selected_trackers": ["AITHER", "HUNO"],
            "tracker_release_data": {
                "AITHER": {"title": "a", "nfo_asset": "nfo/aither.txt"},
                "HUNO": {"title": "h", "nfo_asset": "nfo/huno.txt"},
            },
        }
    }
    job = store.build_job(
        "Two trackers",
        JobSummary(trackers=["Aither", "Huno"]),
        context,
    )
    directory = store.job_dir(working_dir, job.job_id, ensure_exists=True)
    nfo_dir = directory / store.JOB_NFO_DIR_NAME
    nfo_dir.mkdir(parents=True)
    (nfo_dir / "aither.txt").write_text("a", encoding="utf-8")
    (nfo_dir / "huno.txt").write_text("h", encoding="utf-8")
    store.write_job_document(job, directory)
    return job, directory


def _runner() -> JobQueueRunner:
    return JobQueueRunner(backend=SimpleNamespace(), config=SimpleNamespace())


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

    _runner()._settle(job, outcome)

    assert outcome.disposition is JobDisposition.DELETED
    assert not directory.exists()


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

    _runner()._settle(job, outcome)

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

    _runner()._settle(job, outcome)

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

    _runner()._settle(job, outcome)

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

    _runner()._settle(job, outcome)

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

    _runner()._settle(job, outcome)

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

    _runner()._settle(job, outcome)

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

    _runner()._settle(job, outcome)

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

    _runner()._settle(job, outcome)

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

    _runner()._settle(job, outcome)

    assert outcome.disposition is JobDisposition.KEPT
    assert directory.exists()
