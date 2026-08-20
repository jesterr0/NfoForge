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
from html import escape
from pathlib import Path
import traceback
from typing import TYPE_CHECKING, Any, cast

from src.backend.jobs import (
    JobAssetError,
    JobCodecError,
    JobStoreError,
    SavedJob,
    archived_base_is_valid,
    base_torrent_path,
    context_from_dict,
    delete_job,
    filter_context_document,
    load_job,
    prune_unreferenced_nfos,
    read_job_asset,
    rebuild_job_document,
    write_job_document,
)
from src.backend.process import ProcessBackEnd
from src.backend.tracker_run_data import build_tracker_data
from src.backend.upload_retry import TrackerRunOutcome
from src.backend.utils.media_info_utils import clear_restored_mediainfo
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


class JobDisposition(Enum):
    """What the queue did with a job's files once it had run it."""

    KEPT = auto()
    """Left exactly as it was, for a human to look at."""

    NARROWED = auto()
    """Rewritten to hold only the trackers that still need uploading."""

    DELETED = auto()
    """Every tracker uploaded, so there was nothing left to keep."""


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
    disposition: JobDisposition = JobDisposition.KEPT
    """What became of this job's files. See `JobQueueRunner._settle`."""

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
        job_started: Callable[[int, str], None] | None = None,
        job_finished: Callable[[int, QueuedJobOutcome], None] | None = None,
        text_replace_last_update: Callable[[str], None] | None = None,
    ) -> None:
        self.backend = backend
        self.config = config
        self._text_update = text_update or (lambda _message: None)
        self._status_update = status_update or (lambda _tracker, _status: None)
        self._progress_cb = progress_cb or (lambda _value: None)
        self._is_cancelled = is_cancelled or (lambda: False)
        # The queue's own window lists jobs before any of them runs, so it needs
        # to be told when each one starts and ends rather than reconstructing
        # that from the text log.
        self._job_started = job_started or (lambda _index, _name: None)
        self._job_finished = job_finished or (lambda _index, _outcome: None)
        # A caller with no way to rewrite its last line falls back to appending,
        # which is what the queue did for everyone -- leaving both halves of
        # every "running..." / "done" pair in the log.
        self._text_replace_last_update = text_replace_last_update or self._text_update

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
            outcome = self._run_one(path, index)
            self._job_finished(index, outcome)
            results.append(outcome)
        return results

    # ----------------------------------------------------------------------
    def _run_one(self, path: Path, index: int) -> QueuedJobOutcome:
        try:
            job = load_job(path)
        except JobStoreError as error:
            LOG.error(LOG.LOG_SOURCE.BE, f"Queue could not load '{path}': {error}")
            self._job_started(index, path.name)
            return QueuedJobOutcome(
                job_name=path.name,
                path=path,
                result=QueuedJobResult.SKIPPED_UNUSABLE,
                detail=str(error),
            )

        self._job_started(index, job.name)
        self._text_update(f"<br /><span>Loaded <b>{escape(job.name)}</b></span>")

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
                f"<br /><span>⏭ Skipping <b>{escape(job.name)}</b>: "
                f"{escape(detail)}</span>"
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
                f"<br /><span>⏭ Skipping <b>{escape(job.name)}</b>: "
                f"{escape(unusable)}</span>"
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
            input_is_directory=context.media_input.input_is_directory(),
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
                f"<br /><span>⏭ Skipping <b>{escape(job.name)}</b>: "
                f"{escape(detail)}. The job is kept for you to review.</span>"
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

        outcome = self._upload(job, path, context, tracker_data)
        self._settle(job, outcome, context)
        return outcome

    # ----------------------------------------------------------------------
    def _restore(self, job: SavedJob, path: Path) -> ProcessingContext | str:
        """Build a fresh context for this job, or say why it could not be."""
        # never share the wizard's live context, and never inherit MediaInfo
        # cached for whichever job ran before this one
        clear_restored_mediainfo()
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
        if job.archived:
            stored = base_torrent_path(path)
            details = job.context.get("base_torrent")
            snapshot = details.get("snapshot") if isinstance(details, dict) else None
            if stored is None or not archived_base_is_valid(stored, snapshot):
                return "saved base torrent is missing, corrupt, or invalid"
            if isinstance(snapshot, dict):
                content_size = snapshot.get("content_size")
                if isinstance(content_size, int):
                    context.media_input.content_size = content_size
                mode = snapshot.get("mode")
                if mode in {"singlefile", "multifile"}:
                    context.media_input.input_kind = (
                        "directory" if mode == "multifile" else "file"
                    )
            context.shared_data.base_torrent = stored
        return context

    @staticmethod
    def _unusable_reason(context: ProcessingContext) -> str | None:
        """Why this job cannot run, or None when it can."""
        try:
            context.media_input.require_existing_media_paths(include_comparison=False)
        except (FileNotFoundError, RuntimeError) as error:
            if context.shared_data.base_torrent is None:
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
                queued_text_update_replace_last_line=self._text_replace_last_update,
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

    def _settle(
        self, job: SavedJob, outcome: QueuedJobOutcome, context: ProcessingContext
    ) -> None:
        """Bring a job's files into line with what actually uploaded.

        A job left on disk unchanged after uploading is a job the next queue run
        uploads all over again, so a tracker that reached its destination has to
        come out of it. Exactly one thing earns removal: proof the release
        landed. Everything else stays -- never attempted, skipped, provably
        failed, switched off in config, or an upload nobody can account for --
        because each of those is either still to do or still to judge, and the
        job folder is where its prepared torrent and NFO live.

        Framing this as "remove only what provably landed" rather than "keep
        only what is safe to retry" is what makes the awkward outcomes fall out
        correctly. `MAY_HAVE_UPLOADED` is neither retryable nor done, and
        neither is a tracker whose uploads are disabled in config; a two-way
        split counts both as finished and deletes their prepared work.

        The document is rebuilt from the *live* context before any of that.
        Narrowing what was loaded from disk would persist a job that still
        knows nothing of what the run just did -- most consequentially the
        screenshots it uploaded, which the next run would then upload again.
        """
        if not outcome.outcomes:
            # the run never reached the upload stage, so there is nothing to
            # reconcile -- a skipped job is kept for review as it was
            return

        rebuilt = self._rebuild(job, outcome.path, context)

        landed = {
            tracker
            for tracker, tracker_outcome in outcome.outcomes.items()
            if tracker_outcome
            in {TrackerRunOutcome.UPLOADED, TrackerRunOutcome.INJECTION_FAILED}
        }
        if not landed and not job.archived:
            # Nothing reached a tracker, so which trackers the job covers is
            # unchanged -- but what the run produced along the way still has to
            # be written, or the next attempt starts from scratch. A run that
            # added nothing writes nothing, so an untouched job stays untouched
            # on disk rather than being rewritten byte-for-byte.
            if rebuilt:
                self._write(job, outcome.path, "record what this run produced in")
            # It still needs saying when one of them cannot be accounted for.
            self._warn_unconfirmed(job, outcome)
            return

        if job.archived:

            def member_names(values: list[str]) -> set[TrackerSelection]:
                members: set[TrackerSelection] = set()
                for value in values:
                    try:
                        members.add(TrackerSelection[value])
                    except KeyError:
                        continue
                return members

            uploaded = member_names(job.uploaded_trackers) | landed
            uncertain = member_names(job.uncertain_trackers) | {
                tracker
                for tracker, tracker_outcome in outcome.outcomes.items()
                if tracker_outcome is TrackerRunOutcome.MAY_HAVE_UPLOADED
            }
            uncertain -= uploaded
            pending = set(outcome.outcomes) - uploaded - uncertain
            try:
                # an uncertain tracker keeps its prepared title, NFO and image
                # state without being runnable, so resolving it later has
                # something to put back -- see `filter_context_document`
                job.context = filter_context_document(
                    job.context, pending, retain_data_for=uncertain
                )
                job.uploaded_trackers = sorted(tracker.name for tracker in uploaded)
                job.uncertain_trackers = sorted(tracker.name for tracker in uncertain)
                job.summary.trackers = sorted(str(tracker) for tracker in pending)
                job.summary.uploaded_trackers = sorted(
                    str(tracker) for tracker in uploaded
                )
                job.summary.uncertain_trackers = sorted(
                    str(tracker) for tracker in uncertain
                )
                write_job_document(job, outcome.path)
            except (JobStoreError, OSError) as error:
                LOG.error(LOG.LOG_SOURCE.BE, f"Could not update archive: {error}")
                self._text_update(
                    f"<br /><span>⚠️ <b>{escape(job.name)}</b> uploaded, but its "
                    f"archive state could not be updated: {escape(str(error))}</span>"
                )
                return
            try:
                prune_unreferenced_nfos(outcome.path, job.context)
            except OSError as error:
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"Archive updated but stale NFO cleanup failed: {error}",
                )
            outcome.disposition = JobDisposition.NARROWED
            self._text_update(
                f"<br /><span>📦 Updated reusable archive "
                f"<b>{escape(job.name)}</b></span>"
            )
            self._warn_unconfirmed(job, outcome)
            return

        retained = set(outcome.outcomes) - landed
        if not retained:
            try:
                delete_job(outcome.path)
            except JobStoreError as error:
                LOG.error(
                    LOG.LOG_SOURCE.BE, f"Could not remove a finished job: {error}"
                )
                # the one failure that silently re-uploads everywhere next run,
                # so it cannot be log-only
                self._text_update(
                    f"<br /><span>⚠️ <b>{escape(job.name)}</b> uploaded everywhere "
                    "but could not be removed, so it is still saved and will "
                    f"upload again if queued: {escape(str(error))}</span>"
                )
                return
            outcome.disposition = JobDisposition.DELETED
            self._text_update(
                f"<br /><span>🧹 Removed <b>{escape(job.name)}</b>; every tracker "
                "uploaded</span>"
            )
            return

        try:
            job.context = filter_context_document(job.context, retained)
            job.summary.trackers = [
                str(tracker) for tracker in sorted(retained, key=str)
            ]
            write_job_document(job, outcome.path)
        except (JobStoreError, OSError) as error:
            LOG.error(LOG.LOG_SOURCE.BE, f"Could not narrow a finished job: {error}")
            self._text_update(
                f"<br /><span>⚠️ <b>{escape(job.name)}</b> still lists the trackers "
                "that already uploaded and will send to them again if queued: "
                f"{escape(str(error))}</span>"
            )
            return

        # the write is the commit point: from here the document on disk is
        # correct, so the disposition is true even if the tidy-up below fails
        outcome.disposition = JobDisposition.NARROWED
        try:
            prune_unreferenced_nfos(outcome.path, job.context)
        except OSError as error:
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Left stale NFOs behind in {outcome.path}: {error}",
            )

        remaining = ", ".join(str(tracker) for tracker in sorted(retained, key=str))
        self._text_update(
            f"<br /><span>📝 Kept <b>{escape(job.name)}</b> for "
            f"{escape(remaining)}; the trackers that uploaded were removed from "
            "it</span>"
        )
        self._warn_unconfirmed(job, outcome)

    def _rebuild(self, job: SavedJob, path: Path, context: ProcessingContext) -> bool:
        """Re-serialize the run onto `job`, reporting whether anything changed.

        A failure here costs the run's new state but must not cost the job: the
        loaded document is left in place, so the worst case is the job being
        exactly what it was before the run, which is what it was anyway.
        """
        before = job.context
        try:
            job.context = rebuild_job_document(job, path, context)
        except (JobAssetError, JobCodecError, OSError) as error:
            LOG.error(
                LOG.LOG_SOURCE.BE,
                f"Could not re-serialize '{job.name}' after running it: {error}",
            )
            self._text_update(
                f"<br /><span>⚠️ <b>{escape(job.name)}</b> ran, but what it "
                "produced could not be written back to it: "
                f"{escape(str(error))}</span>"
            )
            return False
        return job.context != before

    def _write(self, job: SavedJob, path: Path, what: str) -> bool:
        """Write `job.json`, reporting the failure to the user if it fails."""
        try:
            write_job_document(job, path)
        except (JobStoreError, OSError) as error:
            LOG.error(LOG.LOG_SOURCE.BE, f"Could not {what} a job: {error}")
            self._text_update(
                f"<br /><span>⚠️ Could not {escape(what)} "
                f"<b>{escape(job.name)}</b>: {escape(str(error))}</span>"
            )
            return False
        return True

    def _warn_unconfirmed(self, job: SavedJob, outcome: QueuedJobOutcome) -> None:
        """Name any tracker whose upload could not be established either way.

        The queue can neither retry these nor write them off, so they are the
        one outcome that needs a person. Said whether the job was narrowed or
        left alone, because the question is the same either way.

        Deliberately silent about a tracker whose uploads are switched off in
        config: nothing was sent, but the user is the one who arranged that, so
        reporting it as something to look into would be noise.
        """
        unconfirmed = sorted(
            str(tracker)
            for tracker, tracker_outcome in outcome.outcomes.items()
            if tracker_outcome is TrackerRunOutcome.MAY_HAVE_UPLOADED
        )
        if not unconfirmed:
            return
        self._text_update(
            f"<br /><span>⚠️ Check {escape(', '.join(unconfirmed))} on the "
            f"tracker before running <b>{escape(job.name)}</b> again -- the "
            "upload could not be confirmed either way</span>"
        )


class _LoggingSignal:
    """Stand-in for the Qt error signal `process_trackers` expects.

    The queue has no page to surface errors into, so they go to the log.
    """

    def emit(self, message: str) -> None:
        LOG.error(LOG.LOG_SOURCE.BE, message)
