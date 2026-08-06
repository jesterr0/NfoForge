"""Running prepared jobs back to back, without a user in the loop.

A queue can only run jobs that never stop to ask anything, which is exactly what
a *prepared* job is: its titles, NFOs and prompt answers are already settled, so
`process_trackers()` skips generation and both dialogs. Everything here therefore
refuses to run an unprepared job rather than quietly hanging on a prompt.

Failures never stop the queue. `process_trackers()` is called with no retry
callback, which its own retry path already reads as "run the automatic retries,
then report the failure and move on", so a tracker that is down costs that
tracker and nothing else. Whatever did not upload is handed back so the caller
can save it as a new job.

Deliberately Qt-free: the worker thread that drives this lives in the frontend,
and everything here stays unit testable without one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
import traceback
from typing import TYPE_CHECKING, Any, cast

from src.backend.jobs import (
    JobCodecError,
    JobStoreError,
    SavedJob,
    context_from_dict,
    load_job,
    read_job_asset,
)
from src.backend.process import ProcessBackEnd
from src.backend.tracker_run_data import build_tracker_data
from src.backend.upload_retry import TrackerRunOutcome
from src.backend.utils.media_info_utils import clear_full_mi_str_cache
from src.context.factory import create_processing_context
from src.context.processing_context import ProcessingContext
from src.enums.tracker_selection import TrackerSelection
from src.logger.nfo_forge_logger import LOG
from src.utils.secret_redaction import scrub_secrets

if TYPE_CHECKING:
    from PySide6.QtCore import SignalInstance


class QueuedJobResult(Enum):
    """How one job in the queue ended."""

    UPLOADED = auto()
    SKIPPED_DUPES = auto()
    """Potential duplicates were found, so nothing was uploaded."""

    SKIPPED_UNVERIFIED = auto()
    """A duplicate check could not complete, so the release is unverified."""

    SKIPPED_UNUSABLE = auto()
    """Its media, screenshots or document could not be loaded."""

    SKIPPED_NOT_PREPARED = auto()
    """It would have needed a user, so the queue would not run it."""

    FAILED = auto()
    """The run raised rather than completing."""


@dataclass(frozen=True, slots=True)
class DupeCheckResult:
    """What the duplicate check could and could not establish."""

    found: list[str] = field(default_factory=list)
    """Trackers reporting a possible duplicate."""

    unverified: list[str] = field(default_factory=list)
    """Trackers whose check did not complete, so they proved nothing."""

    def blocks_upload(self) -> bool:
        """Whether this release may be uploaded unattended.

        An unverified tracker counts the same as a found duplicate. The
        interactive flow already stops and asks when a check fails; a queue has
        nobody to ask, so it must not be the one path that uploads a release
        nothing has actually cleared.
        """
        return bool(self.found or self.unverified)


@dataclass(slots=True)
class QueuedJobOutcome:
    """What happened to one job, and what is left over from it."""

    job_name: str
    path: Path
    result: QueuedJobResult
    detail: str = ""
    outcomes: dict[TrackerSelection, TrackerRunOutcome] = field(default_factory=dict)

    def deferrable_trackers(self) -> set[TrackerSelection]:
        """Trackers this job left un-uploaded that are safe to try again."""
        return {
            tracker
            for tracker, outcome in self.outcomes.items()
            if outcome.is_safe_to_reupload()
        }


class JobQueueRunner:
    """Runs saved jobs one at a time, in the order given."""

    def __init__(
        self,
        backend: ProcessBackEnd,
        config: Any,
        text_update: Callable[[str], None] | None = None,
        status_update: Callable[[str, str], None] | None = None,
        progress_cb: Callable[[float], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self.backend = backend
        self.config = config
        self._text_update = text_update or (lambda _message: None)
        self._status_update = status_update or (lambda _tracker, _status: None)
        self._progress_cb = progress_cb or (lambda _value: None)
        self._is_cancelled = is_cancelled or (lambda: False)

    # ----------------------------------------------------------------------
    def run(self, job_paths: list[Path]) -> list[QueuedJobOutcome]:
        """Work through every job, continuing past any that fails."""
        results: list[QueuedJobOutcome] = []
        for index, path in enumerate(job_paths, start=1):
            if self._is_cancelled():
                self._text_update(
                    "<br /><span>⏹ Queue cancelled; remaining jobs untouched</span>"
                )
                break
            self._text_update(
                f'<br /><h3 style="margin-bottom: 0;">▶️ Job {index} of '
                f"{len(job_paths)}</h3>"
            )
            results.append(self._run_one(path))
        return results

    # ----------------------------------------------------------------------
    def _run_one(self, path: Path) -> QueuedJobOutcome:
        try:
            job = load_job(path)
        except JobStoreError as error:
            LOG.error(LOG.LOG_SOURCE.BE, f"Queue could not load '{path}': {error}")
            return QueuedJobOutcome(
                job_name=path.name,
                path=path,
                result=QueuedJobResult.SKIPPED_UNUSABLE,
                detail=str(error),
            )

        self._text_update(f"<br /><span>Loaded <b>{job.name}</b></span>")

        context = self._restore(job, path)
        if isinstance(context, str):
            return QueuedJobOutcome(
                job_name=job.name,
                path=path,
                result=QueuedJobResult.SKIPPED_UNUSABLE,
                detail=context,
            )

        if not context.shared_data.is_prepared():
            # an unprepared job would stop at the prompt-token or overview
            # dialog, which is precisely what a queue cannot answer
            detail = "job is not prepared, so it would need a user to run"
            self._text_update(
                f"<br /><span>⏭ Skipping <b>{job.name}</b>: {detail}</span>"
            )
            return QueuedJobOutcome(
                job_name=job.name,
                path=path,
                result=QueuedJobResult.SKIPPED_NOT_PREPARED,
                detail=detail,
            )

        unusable = self._unusable_reason(context)
        if unusable:
            self._text_update(
                f"<br /><span>⏭ Skipping <b>{job.name}</b>: {unusable}</span>"
            )
            return QueuedJobOutcome(
                job_name=job.name,
                path=path,
                result=QueuedJobResult.SKIPPED_UNUSABLE,
                detail=unusable,
            )

        tracker_data = build_tracker_data(
            working_dir=context.media_input.require_working_dir(),
            input_path=context.media_input.require_input_path(),
            tracker_image_hosts=context.shared_data.tracker_image_hosts,
        )
        if not tracker_data:
            return QueuedJobOutcome(
                job_name=job.name,
                path=path,
                result=QueuedJobResult.SKIPPED_UNUSABLE,
                detail="job has no trackers left to upload to",
            )

        dupes = self._check_dupes(context, tracker_data)
        if dupes.blocks_upload():
            reasons: list[str] = []
            if dupes.found:
                reasons.append(f"possible duplicates on {', '.join(dupes.found)}")
            if dupes.unverified:
                reasons.append(f"could not check {', '.join(dupes.unverified)}")
            detail = "; ".join(reasons)
            self._text_update(
                f"<br /><span>⏭ Skipping <b>{job.name}</b>: {detail}. The job is "
                "kept for you to review.</span>"
            )
            return QueuedJobOutcome(
                job_name=job.name,
                path=path,
                # naming the two apart matters: one says the release is already
                # there, the other says nobody could tell
                result=(
                    QueuedJobResult.SKIPPED_DUPES
                    if dupes.found
                    else QueuedJobResult.SKIPPED_UNVERIFIED
                ),
                detail=detail,
            )

        return self._upload(job, path, context, tracker_data)

    # ----------------------------------------------------------------------
    def _restore(self, job: SavedJob, path: Path) -> ProcessingContext | str:
        """Build a fresh context for this job, or say why it could not be."""
        # never share the wizard's live context, and never inherit MediaInfo
        # cached for whichever job ran before this one
        clear_full_mi_str_cache()
        context = create_processing_context(
            self.config.settings, self.config.plugin_manager
        )
        try:
            context_from_dict(
                job.context, context, lambda name: read_job_asset(path, name)
            )
        except JobCodecError as error:
            LOG.error(
                LOG.LOG_SOURCE.BE, f"Queue could not restore '{job.name}': {error}"
            )
            return str(error)
        return context

    @staticmethod
    def _unusable_reason(context: ProcessingContext) -> str | None:
        """Why this job cannot run, or None when it can."""
        try:
            context.media_input.require_existing_media_paths(include_comparison=False)
        except (FileNotFoundError, RuntimeError) as error:
            return str(error)

        missing = [
            str(image)
            for image in (context.shared_data.loaded_images or ())
            if not image.is_file()
        ]
        # Missing screenshots only matter to a tracker that still has to upload
        # them. Asking the backend keeps this in step with what the run will
        # actually do -- including the case where the image host was changed
        # after preparing, which makes the stored URLs the wrong host's and
        # sends the run back to the local files.
        needs_images = any(
            ProcessBackEnd.needs_local_images(context, tracker, data.img_to)
            for tracker, data in context.shared_data.tracker_image_hosts.items()
        )
        if missing and needs_images:
            return f"{len(missing)} screenshot(s) no longer exist"
        return None

    def _check_dupes(
        self, context: ProcessingContext, tracker_data: dict[str, Any]
    ) -> DupeCheckResult:
        """Ask every tracker whether this release is already there.

        A check that errors leaves that tracker *unverified*, which blocks the
        upload just as a found duplicate does -- see `DupeCheckResult`.
        """
        all_trackers = [str(TrackerSelection(name)) for name in tracker_data]

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(
                self.backend.dupe_checks(
                    processing_queue=[TrackerSelection(x) for x in tracker_data],
                    media_input_payload=context.media_input,
                    media_search_payload=context.media_search,
                )
            )
        except Exception as error:
            LOG.error(
                LOG.LOG_SOURCE.BE,
                f"Queue dupe check failed: {scrub_secrets(str(error))}",
            )
            # the whole check fell over, so nothing at all was cleared
            return DupeCheckResult(unverified=all_trackers)
        finally:
            loop.close()

        found: list[str] = []
        unverified: list[str] = []
        checked = set()
        for tracker, result in results.items():
            _, succeeded, data = result
            checked.add(str(tracker))
            if not succeeded:
                unverified.append(str(tracker))
            elif isinstance(data, list) and data:
                found.append(str(tracker))

        # a tracker the check never reported on is unverified too, rather than
        # silently assumed clean
        unverified.extend(name for name in all_trackers if name not in checked)
        return DupeCheckResult(found=found, unverified=unverified)

    def _upload(
        self,
        job: SavedJob,
        path: Path,
        context: ProcessingContext,
        tracker_data: dict[str, Any],
    ) -> QueuedJobOutcome:
        outcomes: dict[TrackerSelection, TrackerRunOutcome] = {
            TrackerSelection(name): TrackerRunOutcome.NOT_ATTEMPTED
            for name in tracker_data
        }

        def record(tracker: TrackerSelection, outcome: TrackerRunOutcome) -> None:
            outcomes[tracker] = outcome

        try:
            self.backend.process_trackers(
                process_dict=tracker_data,
                queued_status_update=self._status_update,
                queued_text_update=self._text_update,
                queued_text_update_replace_last_line=self._text_update,
                progress_bar_cb=self._progress_cb,
                # `process_trackers` types this as a Qt signal because every
                # other caller has a page to surface errors into; the queue has
                # none, so it takes the same `emit` shape and logs instead
                # quoted so the name is not resolved at runtime -- it is only
                # imported for type checking, and `cast` evaluates its first
                # argument
                caught_error=cast("SignalInstance", _LoggingSignal()),
                context=context,
                # No callbacks: a prepared job has nothing to prompt for, and a
                # null retry callback is already read as "retry automatically,
                # then report and move on" -- exactly the queue's policy.
                token_prompt_cb=None,
                overview_cb=None,
                upload_retry_cb=None,
                run_outcome_cb=record,
            )
        except Exception as error:
            LOG.error(LOG.LOG_SOURCE.BE, scrub_secrets(traceback.format_exc()))
            return QueuedJobOutcome(
                job_name=job.name,
                path=path,
                result=QueuedJobResult.FAILED,
                detail=scrub_secrets(str(error)),
                outcomes=outcomes,
            )

        return QueuedJobOutcome(
            job_name=job.name,
            path=path,
            result=QueuedJobResult.UPLOADED,
            outcomes=outcomes,
        )


class _LoggingSignal:
    """Stand-in for the Qt error signal `process_trackers` expects.

    The queue has no page to surface errors into, so they go to the log.
    """

    def emit(self, message: str) -> None:
        LOG.error(LOG.LOG_SOURCE.BE, message)
