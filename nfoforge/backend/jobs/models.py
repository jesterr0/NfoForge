"""The on-disk shape of a saved job."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nfoforge.backend.jobs.migrations import JOB_SCHEMA_VERSION
from nfoforge.enums.automation import JobState


@dataclass(slots=True)
class JobSummary:
    """The handful of facts the job picker lists jobs by.

    Stored alongside the payload so the picker can describe every saved job
    without deserializing each one in full.
    """

    title: str | None = None
    year: int | None = None
    media_type: str | None = None
    input_name: str | None = None
    file_count: int = 0
    trackers: list[str] = field(default_factory=list)
    uploaded_trackers: list[str] = field(default_factory=list)
    uncertain_trackers: list[str] = field(default_factory=list)
    input_path: str = ""
    """Full path of the media, so the picker can tell a broken job at a glance.

    `input_name` is only the file name, which cannot be checked against the
    filesystem. Jobs saved before this was recorded leave it empty and are
    treated as fine rather than as broken.
    """

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "year": self.year,
            "media_type": self.media_type,
            "input_name": self.input_name,
            "file_count": self.file_count,
            "trackers": list(self.trackers),
            "uploaded_trackers": list(self.uploaded_trackers),
            "uncertain_trackers": list(self.uncertain_trackers),
            "input_path": self.input_path,
        }

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> JobSummary:
        trackers = document.get("trackers")
        uploaded_trackers = document.get("uploaded_trackers")
        uncertain_trackers = document.get("uncertain_trackers")
        return cls(
            title=document.get("title"),
            year=document.get("year"),
            media_type=document.get("media_type"),
            input_name=document.get("input_name"),
            file_count=int(document.get("file_count") or 0),
            trackers=[str(tracker) for tracker in trackers]
            if isinstance(trackers, list)
            else [],
            uploaded_trackers=[str(tracker) for tracker in uploaded_trackers]
            if isinstance(uploaded_trackers, list)
            else [],
            uncertain_trackers=[str(tracker) for tracker in uncertain_trackers]
            if isinstance(uncertain_trackers, list)
            else [],
            input_path=str(document.get("input_path") or ""),
        )


def job_state(value: object) -> JobState:
    """A stored state, or QUEUED for a job written before states existed."""
    try:
        return JobState(str(value))
    except ValueError:
        return JobState.QUEUED


def _dict_or_none(value: object) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


@dataclass(slots=True)
class SavedJob:
    """A configured upload run, persisted so it can be resumed later."""

    job_id: str
    name: str
    created_at: str
    """ISO-8601 UTC timestamp of when the job was saved."""

    nfoforge_version: str
    """Recorded for diagnostics only; loading never gates on it."""

    summary: JobSummary = field(default_factory=JobSummary)
    context: dict[str, Any] = field(default_factory=dict)

    config_profile: str = ""
    """Config profile this job was built under.

    Everything the upload actually depends on -- tracker credentials, NFO
    template names, rename and screenshot rules -- is read live from whatever
    profile is active at resume time, never from the job. Recording the profile
    is what lets the picker refuse to resume a job under settings it was not
    built for.
    """

    schema_version: int = JOB_SCHEMA_VERSION
    archived: bool = False
    """Whether the stored base torrent is the canonical release snapshot."""

    uploaded_trackers: list[str] = field(default_factory=list)
    uncertain_trackers: list[str] = field(default_factory=list)

    state: JobState = JobState.QUEUED
    """Where the job is. A job saved from the desktop app is ready to run."""

    stage: str | None = None
    """The workflow stage the job reached, and resumes at."""

    request: dict[str, Any] | None = None
    """The `ReleaseRequest` that started a headless run, as JSON."""

    pending_decision: dict[str, Any] | None = None
    """The question a waiting job stopped at, as JSON."""

    decision_answers: dict[str, Any] = field(default_factory=dict)
    """Answers given so far, keyed by decision id; reused on resume."""

    error: str | None = None
    """Why a failed job failed."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "name": self.name,
            "created_at": self.created_at,
            "nfoforge_version": self.nfoforge_version,
            "config_profile": self.config_profile,
            "archived": self.archived,
            "uploaded_trackers": list(self.uploaded_trackers),
            "uncertain_trackers": list(self.uncertain_trackers),
            "summary": self.summary.to_dict(),
            "context": self.context,
            "state": str(self.state),
            "stage": self.stage,
            "request": self.request,
            "pending_decision": self.pending_decision,
            "decision_answers": dict(self.decision_answers),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> SavedJob:
        summary = document.get("summary")
        context = document.get("context")
        return cls(
            job_id=str(document.get("job_id") or ""),
            name=str(document.get("name") or ""),
            created_at=str(document.get("created_at") or ""),
            nfoforge_version=str(document.get("nfoforge_version") or ""),
            summary=JobSummary.from_dict(summary if isinstance(summary, dict) else {}),
            context=context if isinstance(context, dict) else {},
            config_profile=str(document.get("config_profile") or ""),
            archived=bool(document.get("archived")),
            uploaded_trackers=[
                str(value) for value in document.get("uploaded_trackers", [])
            ]
            if isinstance(document.get("uploaded_trackers"), list)
            else [],
            uncertain_trackers=[
                str(value) for value in document.get("uncertain_trackers", [])
            ]
            if isinstance(document.get("uncertain_trackers"), list)
            else [],
            schema_version=int(document.get("schema_version") or JOB_SCHEMA_VERSION),
            # Added without a schema bump (see `migrations`): a job written
            # before these existed reads as a queued job with no history.
            state=job_state(document.get("state")),
            stage=str(document["stage"]) if document.get("stage") else None,
            request=_dict_or_none(document.get("request")),
            pending_decision=_dict_or_none(document.get("pending_decision")),
            decision_answers=_dict_or_none(document.get("decision_answers")) or {},
            error=str(document["error"]) if document.get("error") else None,
        )


@dataclass(slots=True, frozen=True)
class JobListing:
    """What the picker needs to show a job, without its payload.

    A job's `context` carries a MediaInfo XML dump per file, so listing every
    saved job as a full `SavedJob` would pull far more into memory than a
    list needs. Load the job from its path once the user actually picks one.
    """

    job_id: str
    name: str
    created_at: str
    summary: JobSummary
    path: Path
    config_profile: str = ""
    prepared: bool = False
    """Whether this job's titles and NFOs are already generated.

    Only a prepared job can be run from the queue: an unprepared one would stop
    at a prompt there is nobody to answer.
    """
    media_available: bool = True
    """Whether the job's media is still where it was saved.

    Checked when the list is built so a job that cannot run is visible as such
    before the user commits to loading it.
    """
    archived: bool = False
    source_less_ready: bool = False
    state: JobState = JobState.QUEUED

    def matches_profile(self, active_profile: str | None) -> bool:
        """Whether this job belongs to the currently active config profile.

        A job saved before profiles were recorded has no profile to compare, so
        it is treated as belonging to whatever is active rather than being
        locked out of every profile.
        """
        if not self.config_profile:
            return True
        return self.config_profile == (active_profile or "")
