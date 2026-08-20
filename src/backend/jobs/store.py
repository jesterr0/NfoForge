"""Reading and writing saved jobs on disk.

Each job is a *directory* under `<working_dir>/jobs/`, not a lone file:

    jobs/<job_id>/
        job.json            the serialized context
        images/             screenshots copied out of harm's way
        mediainfo/          per-file MediaInfo, so the media is never re-read
        base.torrent        clone source, so the media is never re-hashed

Bundling a job's inputs with it is what makes it survivable. Screenshots and
torrents otherwise live under `processing/`, which Settings -> General "Clean
Up" is meant to empty -- a saved job pointing into that tree would be quietly
gutted the first time a user reclaimed disk space. Owning its own copies also
means deleting a job reclaims exactly what it was costing.

`job.json` is written **last**. A directory without it is a half-written job
and is ignored, so a crash mid-save can't produce a job that loads with
missing pieces.

JSON rather than pickle is deliberate: a job file is loaded straight back off
disk, and `src/backend/trackers/cookie_storage.py` already moved off pickle for
exactly that reason -- unpickling a file from a user-writable directory would be
an arbitrary-code-execution path.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any

import shortuuid

from src.backend.jobs.migrations import (
    JOB_SCHEMA_VERSION,
    JobMigrationError,
    migrate_document,
)
from src.backend.jobs.models import JobListing, JobSummary, SavedJob
from src.backend.utils.working_dir import JOBS_DIR_NAME, jobs_dir
from src.config.persistence import atomic_write_text
from src.logger.nfo_forge_logger import LOG
from src.version import __version__

JOB_DOCUMENT_NAME = "job.json"
JOB_IMAGES_DIR_NAME = "images"
JOB_MEDIAINFO_DIR_NAME = "mediainfo"
JOB_NFO_DIR_NAME = "nfo"
JOB_BASE_TORRENT_NAME = "base.torrent"

__all__ = [
    "JOB_BASE_TORRENT_NAME",
    "JOB_DOCUMENT_NAME",
    "JOB_IMAGES_DIR_NAME",
    "JOB_MEDIAINFO_DIR_NAME",
    "JOB_NFO_DIR_NAME",
    "JobStoreError",
    "build_job",
    "delete_job",
    "job_dir",
    "jobs_dir",
    "list_jobs",
    "load_job",
    "prune_unreferenced_nfos",
    "save_job",
    "write_job_document",
]


class JobStoreError(Exception):
    """A job could not be read from or written to disk."""


def _validate_job_id(job_id: str) -> str:
    if (
        not job_id
        or any(char in job_id for char in '\\/:*?"<>|')
        or job_id
        in {
            ".",
            "..",
        }
    ):
        raise JobStoreError(f"Invalid job id: '{job_id}'")
    return job_id


def job_dir(working_dir: Path, job_id: str, ensure_exists: bool = False) -> Path:
    """The directory holding one job and everything it owns."""
    path = jobs_dir(working_dir) / _validate_job_id(job_id)
    if ensure_exists:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _require_job_dir(path: Path) -> None:
    """Guard against a caller handing us a path that isn't a job directory.

    Jobs are addressed by path so they stay findable across several working
    directories; that flexibility must never become a way to delete arbitrary
    folders.
    """
    if path.parent.name != JOBS_DIR_NAME:
        raise JobStoreError(f"Not a saved job directory: '{path}'")


def build_job(
    name: str,
    summary: JobSummary,
    context: dict,
    config_profile: str | None = None,
    *,
    archived: bool = False,
    uploaded_trackers: Iterable[str] = (),
    uncertain_trackers: Iterable[str] = (),
) -> SavedJob:
    """Assemble a `SavedJob` with fresh identity/timestamp fields."""
    return SavedJob(
        job_id=shortuuid.uuid(),
        name=name.strip() or "Untitled job",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        nfoforge_version=str(__version__),
        summary=summary,
        context=context,
        config_profile=config_profile or "",
        schema_version=JOB_SCHEMA_VERSION,
        archived=archived,
        uploaded_trackers=list(uploaded_trackers),
        uncertain_trackers=list(uncertain_trackers),
    )


def write_job_document(job: SavedJob, directory: Path) -> Path:
    """Write `job.json` into a job directory, creating it if needed, and return it.

    `save_job` derives the directory from a working directory plus a job id.
    This takes the directory itself, which is what a caller holding only a
    job's path has -- the queue rewriting a job it just ran, or the picker
    renaming one.
    """
    directory.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.dumps(job.to_dict(), indent=2)
    except (TypeError, ValueError) as error:
        # a plugin or metadata provider can put anything in the free-form
        # fields; failing here rather than escaping as a raw TypeError is what
        # lets the caller clean up the half-written directory
        raise JobStoreError(
            f"Job '{job.name}' contains data that cannot be saved: {error}"
        ) from error
    try:
        atomic_write_text(directory / JOB_DOCUMENT_NAME, payload)
    except OSError as error:
        raise JobStoreError(f"Could not write job to '{directory}': {error}") from error
    return directory


def save_job(job: SavedJob, working_dir: Path) -> Path:
    """Write a job's document into its directory and return that directory.

    Anything the job owns (images, MediaInfo, base torrent) must already have
    been placed in the directory by the caller: this writes `job.json` last so
    the job only becomes visible once it is complete.
    """
    directory = write_job_document(job, job_dir(working_dir, job.job_id))
    LOG.info(LOG.LOG_SOURCE.BE, f"Saved job '{job.name}' to {directory}")
    return directory


def prune_unreferenced_nfos(directory: Path, context: dict[str, Any]) -> None:
    """Delete NFO sidecars a job's context no longer points at.

    Narrowing a job to fewer trackers leaves the dropped trackers' NFOs behind.
    They are dead weight, and worse, they read as evidence the job still covers
    those trackers.

    A malformed context must not read as "references nothing": that would
    delete every NFO the job owns instead of the handful a narrowing dropped.
    So a missing or wrong-typed `tracker_release_data` bails out with nothing
    touched, while a `tracker_release_data` that is present but genuinely
    empty (a job with no NFOs at all) still prunes -- that mapping deliberately
    driving zero references is not the same as not having one to read.
    """
    nfo_dir = directory / JOB_NFO_DIR_NAME
    if not nfo_dir.is_dir():
        return

    shared = context.get("shared_data")
    if not isinstance(shared, dict):
        LOG.warning(
            LOG.LOG_SOURCE.BE,
            f"Not pruning NFOs in '{directory}': context has no 'shared_data' mapping",
        )
        return
    release_data = shared.get("tracker_release_data")
    if not isinstance(release_data, dict):
        LOG.warning(
            LOG.LOG_SOURCE.BE,
            f"Not pruning NFOs in '{directory}': context has no "
            "'tracker_release_data' mapping",
        )
        return

    referenced: set[str] = set()
    for entry in release_data.values():
        if not isinstance(entry, dict):
            continue
        name = entry.get("nfo_asset")
        if isinstance(name, str) and name:
            referenced.add(Path(name).name)

    for candidate in nfo_dir.iterdir():
        if candidate.is_file() and candidate.name not in referenced:
            candidate.unlink(missing_ok=True)


def _read_document(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise JobStoreError(f"Could not read job '{path}': {error}") from error
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise JobStoreError(f"Job file '{path}' is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise JobStoreError(f"Job file '{path}' is not a job document")
    return document


def load_job(directory: Path) -> SavedJob:
    """Load a job directory, migrating its document to the current schema."""
    _require_job_dir(directory)
    document_path = directory / JOB_DOCUMENT_NAME
    if not document_path.is_file():
        raise JobStoreError(f"No saved job at '{directory}'")
    document = _read_document(document_path)
    try:
        document = migrate_document(document)
    except JobMigrationError as error:
        raise JobStoreError(str(error)) from error
    return SavedJob.from_dict(document)


def _document_is_prepared(document: dict) -> bool:
    """Whether a job document carries finished titles/NFOs.

    Read straight from the document so the picker can tell without paying to
    deserialize every job it lists.

    Kept in step with `SharedPayload.is_prepared()`, including its answer for a
    job that selects no tracker at all: there is nothing to be prepared for, so
    retained release data does not make it runnable.
    """
    context = document.get("context")
    if not isinstance(context, dict):
        return False
    shared = context.get("shared_data")
    if not isinstance(shared, dict):
        return False
    release_data = shared.get("tracker_release_data")
    selected = shared.get("selected_trackers")
    if not isinstance(release_data, dict):
        return False
    if not isinstance(selected, list) or not selected:
        return False
    return all(name in release_data for name in selected)


def list_jobs(working_dirs: Iterable[Path]) -> list[JobListing]:
    """List saved jobs across every given working directory, newest first.

    A job that cannot be read is logged and skipped rather than taking the whole
    list down with it, and a directory without `job.json` is treated as a
    half-written save and ignored. Working directories are de-duplicated so
    profiles that share one don't list the same job twice.
    """
    listings: list[JobListing] = []
    seen_dirs: set[Path] = set()

    for working_dir in working_dirs:
        directory = jobs_dir(working_dir)
        resolved = directory.resolve() if directory.exists() else directory
        if resolved in seen_dirs:
            continue
        seen_dirs.add(resolved)
        if not directory.is_dir():
            continue

        for candidate in sorted(directory.iterdir()):
            document_path = candidate / JOB_DOCUMENT_NAME
            if not candidate.is_dir() or not document_path.is_file():
                continue
            try:
                document = _read_document(document_path)
            except JobStoreError as error:
                LOG.warning(LOG.LOG_SOURCE.BE, f"Skipping unreadable job: {error}")
                continue
            summary_document = document.get("summary")
            summary = JobSummary.from_dict(
                summary_document if isinstance(summary_document, dict) else {}
            )
            # cheap enough to do per job, and it is the difference between the
            # user finding out here and finding out after clicking Load
            media_available = (
                Path(summary.input_path).exists() if summary.input_path else True
            )
            context = document.get("context")
            media_section = (
                context.get("media_input") if isinstance(context, dict) else None
            )
            has_mediainfo = isinstance(media_section, dict) and bool(
                media_section.get("mediainfo_assets")
                or media_section.get("mediainfo_xml")
            )
            source_less_ready = bool(
                document.get("archived")
                and (candidate / JOB_BASE_TORRENT_NAME).is_file()
                and has_mediainfo
            )
            listings.append(
                JobListing(
                    job_id=str(document.get("job_id") or candidate.name),
                    name=str(document.get("name") or candidate.name),
                    created_at=str(document.get("created_at") or ""),
                    config_profile=str(document.get("config_profile") or ""),
                    summary=summary,
                    prepared=_document_is_prepared(document),
                    path=candidate,
                    media_available=media_available,
                    archived=bool(document.get("archived")),
                    source_less_ready=source_less_ready,
                )
            )

    listings.sort(key=lambda listing: listing.created_at, reverse=True)
    return listings


def delete_job(directory: Path) -> None:
    """Remove a saved job and everything it owns."""
    _require_job_dir(directory)
    try:
        shutil.rmtree(directory, ignore_errors=False)
    except FileNotFoundError:
        return
    except OSError as error:
        raise JobStoreError(f"Could not delete job '{directory}': {error}") from error
    LOG.info(LOG.LOG_SOURCE.BE, f"Deleted job {directory}")
