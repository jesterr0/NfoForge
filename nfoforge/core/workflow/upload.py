"""The upload stage's shared parts: duplicate checks and the per-tracker data.

The desktop Process page, the job queue and a headless run all upload through
`ProcessBackEnd.process_trackers`. What comes before it -- asking every
tracker whether it already has the release, and building the data the run
consumes -- lives here, so all three settle it the same way. How each responds
differs: the page shows the matches and lets the user decide, the queue skips
the job, a headless run raises a decision per tracker.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nfoforge.backend.tracker_run_data import build_tracker_data
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.core.workflow.decisions import Decision, DecisionKind
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.logger.nfo_forge_logger import LOG
from nfoforge.utils.secret_redaction import scrub_secrets

if TYPE_CHECKING:
    from nfoforge.backend.process import ProcessBackEnd


@dataclass(frozen=True, slots=True)
class DupeCheckResult:
    """What the duplicate check could and could not establish."""

    found: list[str] = field(default_factory=list)
    """Trackers reporting a possible duplicate."""

    unverified: list[str] = field(default_factory=list)
    """Trackers whose check did not complete, so they proved nothing."""

    matches: dict[str, list[Any]] = field(default_factory=dict)
    """Each `found` tracker's possible duplicates (`TrackerSearchResult`s)."""

    errors: dict[str, str] = field(default_factory=dict)
    """Why each `unverified` tracker's check did not complete."""

    failure: str | None = None
    """Set when the whole check fell over, rather than one tracker's."""

    def blocks_upload(self) -> bool:
        """Whether this release may be uploaded unattended.

        An unverified tracker counts the same as a found duplicate. The
        interactive flow stops and asks when a check fails; an unattended run
        has nobody to ask, so it must not be the one path that uploads a
        release nothing has actually cleared.
        """
        return bool(self.found or self.unverified)

    def clears(self, tracker: TrackerSelection | str) -> bool:
        """Whether `tracker` was checked and reported no duplicate."""
        name = str(tracker)
        return name not in self.found and name not in self.unverified


async def check_dupes(
    backend: ProcessBackEnd,
    context: ProcessingContext,
    trackers: Iterable[TrackerSelection],
) -> DupeCheckResult:
    """Ask every tracker whether this release is already there.

    Never raises: a check that errors leaves that tracker unverified, and a
    tracker the check never reported on is unverified too rather than silently
    assumed clean.
    """
    trackers = list(trackers)
    names = [str(tracker) for tracker in trackers]
    try:
        results = await backend.dupe_checks(
            processing_queue=trackers,
            media_input_payload=context.media_input,
            media_search_payload=context.media_search,
        )
    except Exception as error:
        reason = scrub_secrets(str(error)) or type(error).__name__
        LOG.error(LOG.LOG_SOURCE.BE, f"Duplicate check failed: {reason}")
        return DupeCheckResult(
            unverified=names,
            errors=dict.fromkeys(names, reason),
            failure=reason,
        )

    found: list[str] = []
    unverified: list[str] = []
    matches: dict[str, list[Any]] = {}
    errors: dict[str, str] = {}
    for tracker, result in results.items():
        _, succeeded, data = result
        name = str(tracker)
        if not succeeded:
            unverified.append(name)
            errors[name] = str(data)
        elif isinstance(data, list) and data:
            found.append(name)
            matches[name] = list(data)
    reported = {str(tracker) for tracker in results}
    for name in names:
        if name not in reported:
            unverified.append(name)
            errors[name] = "not checked"
    return DupeCheckResult(found, unverified, matches, errors)


def check_dupes_blocking(
    backend: ProcessBackEnd,
    context: ProcessingContext,
    trackers: Iterable[TrackerSelection],
) -> DupeCheckResult:
    """`check_dupes` for a caller with no event loop running (a worker thread)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(check_dupes(backend, context, trackers))
    finally:
        loop.close()


def dupe_decision(
    tracker: TrackerSelection, result: DupeCheckResult
) -> Decision | None:
    """The question `tracker`'s duplicate check leaves, or None if it cleared."""
    name = str(tracker)
    if name in result.found:
        return Decision(
            DecisionKind.DUPES_FOUND,
            f"{name} may already have this release. Upload anyway?",
            subject=tracker.name,
            hint="pass --skip-dupe-check to upload past it",
            context={
                "matches": [
                    str(getattr(item, "name", item))
                    for item in result.matches.get(name, [])
                ]
            },
        )
    if name in result.unverified:
        return Decision(
            DecisionKind.DUPE_CHECK_FAILED,
            f"{name} could not be checked for duplicates "
            f"({result.errors.get(name, 'unknown error')}). Upload anyway?",
            subject=tracker.name,
            hint="pass --skip-dupe-check to upload without checking",
        )
    return None


def run_tracker_data(context: ProcessingContext) -> dict[str, dict[str, Any]]:
    """The per-tracker work items `process_trackers` consumes, for this run."""
    return build_tracker_data(
        working_dir=context.media_input.require_working_dir(),
        input_path=context.media_input.require_input_path(),
        tracker_image_hosts=context.shared_data.tracker_image_hosts,
        input_is_directory=context.media_input.input_is_directory(),
    )
