"""Running a release from a path to its trackers, without any interface.

`Workflow.start` takes a `ReleaseRequest` and walks the stages `plan_stages`
lays out, calling `steps.STEPS` for each. It reports only through an
`EventSink` and asks only through a `DecisionPolicy`, so the same run can be
driven from a terminal, a server or a test.

A run that stops at a question it cannot answer (safe mode) is saved as a job
waiting for input, with everything done so far. `Workflow.resume` restores it
and carries on from the stage it stopped at, with the answer. A run that fails
is saved too, as failed, once there is anything to save. A run that uploads is
archived like any desktop run, so trackers can be added to it later.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
import traceback
from typing import TYPE_CHECKING, Any

from nfoforge.backend.images import ImagesBackEnd
from nfoforge.backend.jobs import (
    JobAssetError,
    JobCodecError,
    JobStoreError,
    archive_completed_run,
    build_job_document,
    context_from_dict,
    default_job_name,
    load_job,
    read_job_asset,
    save_new_job,
    write_job_document,
)
from nfoforge.backend.media_search import MediaSearchBackEnd
from nfoforge.backend.process import ProcessBackEnd
from nfoforge.backend.upload_retry import TrackerRunOutcome
from nfoforge.backend.utils.media_info_utils import clear_restored_mediainfo
from nfoforge.context.factory import create_processing_context
from nfoforge.core.workflow.decisions import (
    Answered,
    Decision,
    DecisionPolicy,
    DecisionStop,
    Pending,
    Resolution,
    policy_for,
)
from nfoforge.core.workflow.events import (
    DecisionNeeded,
    EventSink,
    JobStateChanged,
    LoggingSink,
    LogLevel,
    LogLine,
    StageFinished,
    StageStarted,
)
from nfoforge.core.workflow.request import ReleaseRequest
from nfoforge.core.workflow.stages import RoutingOptions, Stage, next_stage
from nfoforge.core.workflow.steps import STEPS, Run, WorkflowError
from nfoforge.enums.automation import JobState
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.utils.secret_redaction import scrub_secrets

if TYPE_CHECKING:
    from nfoforge.config.config import ConfigManager

_SAVE_ERRORS = (JobAssetError, JobCodecError, JobStoreError, OSError, RuntimeError)


@dataclass(slots=True)
class WorkflowResult:
    """How a run ended."""

    state: JobState
    stage: Stage
    """The stage it finished at, or stopped or failed in."""
    job_path: Path | None = None
    """The saved job, when one was written: waiting, failed, or the archive."""
    error: str | None = None
    decision: Decision | None = None
    """The question a waiting or refused run stopped at."""
    outcomes: dict[TrackerSelection, TrackerRunOutcome] = field(default_factory=dict)


class _RecordingPolicy:
    """Keeps every answer given, so a saved job can reuse it on resume."""

    def __init__(self, inner: DecisionPolicy, answers: dict[str, Any]) -> None:
        self._inner = inner
        self._answers = answers

    def resolve(self, decision: Decision, /) -> Resolution:
        resolution = self._inner.resolve(decision)
        if isinstance(resolution, Answered):
            self._answers[decision.id] = resolution.value
        return resolution


def routing_for(request: ReleaseRequest, settings: Any) -> RoutingOptions:
    """The optional stages this run goes through, with the request's say."""
    profile = RoutingOptions.from_settings(settings)
    rename = request.rename
    if request.no_screenshots:
        screenshots = False
    elif request.screenshot_dir is not None:
        screenshots = True
    else:
        screenshots = profile.screenshots
    return RoutingOptions(
        rename_movies=profile.rename_movies if rename is None else rename,
        rename_series=profile.rename_series if rename is None else rename,
        screenshots=screenshots,
    )


class Workflow:
    def __init__(
        self,
        config: ConfigManager,
        *,
        sink: EventSink | None = None,
        ask: Callable[[Decision], Any] | None = None,
        process_backend: ProcessBackEnd | None = None,
        search_backend: MediaSearchBackEnd | None = None,
        images_backend: ImagesBackEnd | None = None,
    ) -> None:
        """`ask` puts a question to a person; interactive runs need it."""
        settings = config.settings
        self.config = config
        self.sink = sink or LoggingSink()
        self.ask = ask
        self.process_backend = process_backend or ProcessBackEnd(config)
        self.search_backend = search_backend or MediaSearchBackEnd(
            language=settings.general.tmdb_language,
            timeout=settings.general.timeout,
            api_key=settings.api_keys.tmdb_api_key,
        )
        self.images_backend = images_backend or ImagesBackEnd()

    # -- entry points ----------------------------------------------------
    def start(
        self, request: ReleaseRequest, answers: Mapping[str, Any] | None = None
    ) -> WorkflowResult:
        """Run `request` from the beginning.

        `answers` are given in advance, keyed by `Decision.id`.
        """
        context = create_processing_context(
            self.config.settings, self.config.plugin_manager
        )
        return self._run(request, context, Stage.INPUT, dict(answers or {}), None)

    def resume(
        self, job_path: Path, answers: Mapping[str, Any] | None = None
    ) -> WorkflowResult:
        """Carry on a saved headless job from the stage it stopped at.

        `answers` settle the question it was waiting on (and any others),
        keyed by `Decision.id`; they are added to the answers already given.
        """
        try:
            job = load_job(job_path)
        except _SAVE_ERRORS as error:
            return WorkflowResult(JobState.FAILED, Stage.INPUT, job_path, str(error))
        if not job.request:
            return WorkflowResult(
                JobState.FAILED,
                Stage.INPUT,
                job_path,
                "This job was not started by a headless run, so it has no "
                "request to resume. Open it in NfoForge instead.",
            )
        request = ReleaseRequest.from_dict(job.request)
        stage = Stage(job.stage) if job.stage else Stage.INPUT

        # never inherit MediaInfo cached for whichever job ran before this one
        clear_restored_mediainfo()
        context = create_processing_context(
            self.config.settings, self.config.plugin_manager
        )
        try:
            context_from_dict(
                job.context, context, lambda name: read_job_asset(job_path, name)
            )
        except JobCodecError as error:
            return WorkflowResult(JobState.FAILED, stage, job_path, str(error))
        context.loaded_job_path = job_path
        context.loaded_job_id = job.job_id
        context.loaded_job_name = job.name

        return self._run(
            request,
            context,
            stage,
            dict(job.decision_answers) | dict(answers or {}),
            job_path,
        )

    # -- the run ---------------------------------------------------------
    def _run(
        self,
        request: ReleaseRequest,
        context: Any,
        start: Stage,
        answers: dict[str, Any],
        job_path: Path | None,
    ) -> WorkflowResult:
        policy = _RecordingPolicy(
            policy_for(request.mode, ask=self.ask, answers=answers), answers
        )
        run = Run(
            config=self.config,
            request=request,
            context=context,
            policy=policy,
            sink=self.sink,
            process_backend=self.process_backend,
            search_backend=self.search_backend,
            images_backend=self.images_backend,
        )
        routing = routing_for(request, self.config.settings)
        self.sink.emit(JobStateChanged(JobState.RUNNING))

        stage: Stage | None = start
        while stage is not None:
            run.stage = stage
            self.sink.emit(StageStarted(str(stage)))
            try:
                STEPS[stage](run)
            except DecisionStop as stop:
                return self._stopped(run, stop, answers, job_path)
            except WorkflowError as error:
                return self._failed(run, str(error), answers, job_path)
            except Exception as error:
                self.sink.emit(
                    LogLine(scrub_secrets(traceback.format_exc()), LogLevel.DEBUG)
                )
                return self._failed(
                    run, f"{type(error).__name__}: {error}", answers, job_path
                )
            self.sink.emit(StageFinished(str(stage)))
            stage = next_stage(stage, context.media_search.media_type, routing)

        return self._completed(run, answers, job_path)

    def _stopped(
        self,
        run: Run,
        stop: DecisionStop,
        answers: dict[str, Any],
        job_path: Path | None,
    ) -> WorkflowResult:
        decision = stop.decision
        self.sink.emit(DecisionNeeded(decision.to_dict()))
        if isinstance(stop.resolution, Pending):
            path = self._save(
                run, JobState.WAITING_FOR_INPUT, answers, job_path, decision=decision
            )
            self.sink.emit(JobStateChanged(JobState.WAITING_FOR_INPUT, decision.prompt))
            return WorkflowResult(
                JobState.WAITING_FOR_INPUT,
                run.stage,
                path,
                None if path else "The job could not be saved to wait for input",
                decision,
                dict(run.outcomes),
            )
        return self._failed(run, str(stop), answers, job_path, decision=decision)

    def _failed(
        self,
        run: Run,
        error: str,
        answers: dict[str, Any],
        job_path: Path | None,
        decision: Decision | None = None,
    ) -> WorkflowResult:
        error = scrub_secrets(error)
        self.sink.emit(LogLine(error, LogLevel.ERROR))
        path = self._save(run, JobState.FAILED, answers, job_path, error=error)
        self.sink.emit(JobStateChanged(JobState.FAILED, error))
        return WorkflowResult(
            JobState.FAILED, run.stage, path, error, decision, dict(run.outcomes)
        )

    def _completed(
        self, run: Run, answers: dict[str, Any], job_path: Path | None
    ) -> WorkflowResult:
        path = job_path
        if run.uploaded and run.outcomes:
            try:
                archive = archive_completed_run(
                    run.context,
                    run.outcomes,
                    working_dir=self.config.settings.general.working_dir,
                    config_profile=self.config.program.current_config,
                )
                path = run.context.loaded_job_path
                if path is not None:
                    archive.state = JobState.COMPLETE
                    archive.stage = str(run.stage)
                    archive.request = run.request.to_dict()
                    archive.pending_decision = None
                    archive.decision_answers = dict(answers)
                    archive.error = None
                    write_job_document(archive, path)
            except _SAVE_ERRORS as error:
                self.sink.emit(
                    LogLine(
                        f"The run's archive could not be saved: {error}", LogLevel.ERROR
                    )
                )
        self.sink.emit(JobStateChanged(JobState.COMPLETE))
        return WorkflowResult(
            JobState.COMPLETE, run.stage, path, outcomes=dict(run.outcomes)
        )

    def _save(
        self,
        run: Run,
        state: JobState,
        answers: dict[str, Any],
        job_path: Path | None,
        *,
        decision: Decision | None = None,
        error: str | None = None,
    ) -> Path | None:
        """Write the run as a job, or say why it could not be. Returns its path.

        Nothing is saved for a run that never read its input: there is no
        release to save yet, and starting over costs nothing.
        """
        context = run.context
        if run.request.dry_run or not context.media_input.file_list_mediainfo:
            return None
        try:
            if job_path is None:
                job, job_path = save_new_job(
                    context,
                    name=default_job_name(context),
                    working_dir=self.config.settings.general.working_dir,
                    config_profile=self.config.program.current_config,
                )
            else:
                job = load_job(job_path)
                job.context = build_job_document(context, job_path)
            job.state = state
            job.stage = str(run.stage)
            job.request = run.request.to_dict()
            job.pending_decision = decision.to_dict() if decision else None
            job.decision_answers = dict(answers)
            job.error = error
            write_job_document(job, job_path)
        except _SAVE_ERRORS as save_error:
            self.sink.emit(
                LogLine(f"The job could not be saved: {save_error}", LogLevel.ERROR)
            )
            return None
        return job_path
