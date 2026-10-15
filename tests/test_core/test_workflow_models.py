"""Requests, events, decisions and job state -- the models a run is built from."""

import json
from pathlib import Path

import pytest

from nfoforge.backend.jobs import SavedJob, build_job, list_jobs, load_job, save_job
from nfoforge.backend.jobs.models import JobSummary
from nfoforge.core.workflow.decisions import (
    DECLINED,
    Answered,
    Decision,
    DecisionKind,
    DecisionStop,
    InteractivePolicy,
    Pending,
    Refused,
    SafePolicy,
    UnattendedPolicy,
    policy_for,
    require,
)
from nfoforge.core.workflow.events import (
    CollectingSink,
    FanOutSink,
    JobStateChanged,
    LogLevel,
    LogLine,
    ProgressEvent,
    StageStarted,
)
from nfoforge.core.workflow.request import ReleaseRequest
from nfoforge.enums.automation import AutomationMode, JobState

PICK = Decision(
    DecisionKind.SEARCH_RESULT,
    "Which result is this release?",
    options=("movie-1", "movie-2"),
    hint="pass --tmdb-id",
)
DUPES = Decision(DecisionKind.DUPES_FOUND, "Upload anyway?", subject="AITHER")


# --------------------------------------------------------------------------
# requests
# --------------------------------------------------------------------------
def test_a_request_round_trips_through_json() -> None:
    request = ReleaseRequest(
        path=Path("/media/Movie.2024"),
        trackers=("AITHER", "HUNO"),
        mode=AutomationMode.SAFE,
        tmdb_id="42",
        screenshot_dir=Path("/shots"),
        token_overrides={"edition": "Directors Cut"},
    )

    restored = ReleaseRequest.from_dict(json.loads(json.dumps(request.to_dict())))

    assert restored == request


def test_a_request_ignores_unknown_keys_and_needs_a_path() -> None:
    assert ReleaseRequest.from_dict({"path": "x", "later_field": 1}).path == Path("x")
    with pytest.raises(ValueError, match="path"):
        ReleaseRequest.from_dict({"trackers": []})


# --------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------
def test_events_serialize_with_their_kind() -> None:
    assert ProgressEvent("screenshots", "Generating", current=3, total=6).to_dict() == {
        "kind": "progress",
        "stage": "screenshots",
        "message": "Generating",
        "current": 3,
        "total": 6,
        "percent": None,
    }
    assert json.dumps(JobStateChanged(JobState.FAILED, "boom").to_dict())


def test_sinks_collect_and_fan_out() -> None:
    first, second = CollectingSink(), CollectingSink()
    sink = FanOutSink(first, second)

    sink.emit(StageStarted("search"))
    sink.emit(LogLine("hello", LogLevel.WARNING))

    assert first.events == second.events
    assert [event.message for event in first.of(LogLine)] == ["hello"]


# --------------------------------------------------------------------------
# decisions
# --------------------------------------------------------------------------
def test_decision_ids_are_stable_and_round_trip() -> None:
    assert PICK.id == "search_result"
    assert DUPES.id == "dupes_found:AITHER"
    assert Decision.from_dict(json.loads(json.dumps(DUPES.to_dict()))) == DUPES


def test_every_policy_uses_answers_given_in_advance() -> None:
    answers = {PICK.id: "movie-2"}

    for policy in (
        InteractivePolicy(lambda _d: pytest.fail("asked"), answers),
        SafePolicy(answers),
        UnattendedPolicy(answers),
    ):
        assert policy.resolve(PICK) == Answered("movie-2")


def test_interactive_asks_and_respects_a_decline() -> None:
    assert InteractivePolicy(lambda d: d.options[0]).resolve(PICK) == Answered(
        "movie-1"
    )
    refused = InteractivePolicy(lambda _d: DECLINED).resolve(PICK)
    assert isinstance(refused, Refused)


def test_safe_waits_and_unattended_refuses_naming_the_way_out() -> None:
    assert SafePolicy().resolve(PICK) == Pending(PICK)

    refused = UnattendedPolicy().resolve(PICK)
    assert isinstance(refused, Refused)
    assert "--tmdb-id" in refused.reason


def test_no_policy_takes_the_default_on_its_own() -> None:
    decision = Decision(DecisionKind.DUPES_FOUND, "Upload anyway?", default=True)

    assert not isinstance(UnattendedPolicy().resolve(decision), Answered)
    assert not isinstance(SafePolicy().resolve(decision), Answered)


def test_policy_for_mode() -> None:
    assert isinstance(policy_for(AutomationMode.SAFE), SafePolicy)
    assert isinstance(policy_for(AutomationMode.UNATTENDED), UnattendedPolicy)
    assert isinstance(
        policy_for(AutomationMode.INTERACTIVE, ask=lambda _d: 1), InteractivePolicy
    )
    with pytest.raises(ValueError, match="interactive"):
        policy_for(AutomationMode.INTERACTIVE)


def test_require_returns_the_answer_or_stops() -> None:
    assert require(SafePolicy({PICK.id: "movie-1"}), PICK) == "movie-1"

    with pytest.raises(DecisionStop) as stopped:
        require(SafePolicy(), PICK)
    assert stopped.value.decision == PICK
    assert isinstance(stopped.value.resolution, Pending)


# --------------------------------------------------------------------------
# job state
# --------------------------------------------------------------------------
def test_a_job_written_before_states_existed_reads_as_queued() -> None:
    job = SavedJob.from_dict(
        {
            "schema_version": 1,
            "job_id": "abc",
            "name": "Old job",
            "created_at": "2026-01-01T00:00:00Z",
            "nfoforge_version": "1.0.0",
        }
    )

    assert job.state is JobState.QUEUED
    assert (job.stage, job.request, job.pending_decision, job.error) == (
        None,
        None,
        None,
        None,
    )
    assert job.decision_answers == {}


def test_a_waiting_job_round_trips_through_the_store(tmp_path: Path) -> None:
    job = build_job(name="Waiting", summary=JobSummary(), context={})
    job.state = JobState.WAITING_FOR_INPUT
    job.stage = "search"
    job.request = ReleaseRequest(path=Path("/media/x")).to_dict()
    job.pending_decision = PICK.to_dict()
    job.decision_answers = {"mal_id": 42}

    path = save_job(job, tmp_path)
    restored = load_job(path)

    assert restored.state is JobState.WAITING_FOR_INPUT
    assert restored.stage == "search"
    assert ReleaseRequest.from_dict(restored.request or {}).path == Path("/media/x")
    assert Decision.from_dict(restored.pending_decision or {}) == PICK
    assert restored.decision_answers == {"mal_id": 42}
    assert list_jobs([tmp_path])[0].state is JobState.WAITING_FOR_INPUT
