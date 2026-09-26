"""The `nfoforge` command line."""

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nfoforge.backend.upload_retry import TrackerRunOutcome
from nfoforge.cli import app as cli_app, main as cli_main
from nfoforge.cli.app import CliError, choose_profile
from nfoforge.cli.console import ConsoleSink, TerminalPrompter, is_interactive
from nfoforge.cli.exit_codes import ExitCode
from nfoforge.cli.main import build_parser, main, parse_answer, report
from nfoforge.config.presets import RunPreset
from nfoforge.core.workflow.decisions import DECLINED, Decision, DecisionKind
from nfoforge.core.workflow.engine import WorkflowResult
from nfoforge.core.workflow.events import LogLevel, LogLine, ProgressEvent, StageStarted
from nfoforge.core.workflow.request import ReleaseRequest
from nfoforge.core.workflow.stages import Stage
from nfoforge.enums.automation import AutomationMode, JobState
from nfoforge.enums.tracker_selection import TrackerSelection


# --------------------------------------------------------------------------
# small pieces
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("yes", True),
        ("N", False),
        ("2", 2),
        (
            '{"a.mkv": {"season": 1, "episode": 2}}',
            {"a.mkv": {"season": 1, "episode": 2}},
        ),
        ("tt0133093", "tt0133093"),
    ],
)
def test_parse_answer(text: str, value: Any) -> None:
    assert parse_answer(text) == value


def test_upload_arguments() -> None:
    args = build_parser().parse_args(
        [
            "-c",
            "main",
            "upload",
            "x.mkv",
            "--trackers",
            "AITHER,HUNO",
            "--no-rename",
            "--token",
            "prompt_notes=hi",
        ]
    )

    assert args.config == "main"
    assert args.trackers == "AITHER,HUNO"
    assert args.rename is False
    assert args.no_screenshots is None
    assert args.token == ["prompt_notes=hi"]


def test_several_profiles_need_a_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_app, "available_profiles", lambda: ["a", "b"])

    assert choose_profile("a.toml") == "a"
    with pytest.raises(CliError, match="--config: a, b"):
        choose_profile(None)
    with pytest.raises(CliError, match="No profile named"):
        choose_profile("c")

    monkeypatch.setattr(cli_app, "available_profiles", lambda: ["only"])
    assert choose_profile(None) == "only"


def test_no_input_means_nobody_to_ask() -> None:
    assert not is_interactive(no_input=True)
    assert not is_interactive(io.StringIO(), io.StringIO())


# --------------------------------------------------------------------------
# console
# --------------------------------------------------------------------------
def test_the_console_sink_splits_streams_and_skips_piped_progress() -> None:
    out, err = io.StringIO(), io.StringIO()
    sink = ConsoleSink(out, err)

    sink.emit(StageStarted("series_match"))
    sink.emit(ProgressEvent("screenshots", "Generating", 1, 6))
    sink.emit(LogLine("found it"))
    sink.emit(LogLine("careful", LogLevel.WARNING))
    sink.emit(LogLine("broke", LogLevel.ERROR))
    sink.emit(LogLine("noise", LogLevel.DEBUG))

    assert out.getvalue() == "== series match ==\nfound it\n"
    assert err.getvalue() == "warning: careful\nerror: broke\n"
    assert sink.shown_errors == {"broke"}


def _ask(decision: Decision, typed: str) -> Any:
    return TerminalPrompter(io.StringIO(typed), io.StringIO())(decision)


def test_the_prompter_asks_each_kind_its_own_way() -> None:
    choice = Decision(
        DecisionKind.SEARCH_RESULT, "Which?", options=("603", "604"), default="603"
    )
    assert _ask(choice, "2\n") == "604"
    assert _ask(choice, "\n") == "603"
    assert _ask(choice, "9\nq\n") is DECLINED

    dupes = Decision(DecisionKind.DUPES_FOUND, "Upload anyway?", subject="AITHER")
    assert _ask(dupes, "y\n") is True
    assert _ask(dupes, "\n") is False
    assert _ask(dupes, "") is DECLINED

    tokens = Decision(
        DecisionKind.PROMPT_TOKENS, "Tokens", context={"tokens": ["a", "b"]}
    )
    assert _ask(tokens, "one\ntwo\n") == {"a": "one", "b": "two"}

    episodes = Decision(
        DecisionKind.EPISODE_MAPPING, "Map", context={"files": ["x.mkv", "y.mkv"]}
    )
    assert _ask(episodes, "S01E02\nbad\n1 3\n") == {
        "x.mkv": {"season": 1, "episode": 2},
        "y.mkv": {"season": 1, "episode": 3},
    }

    assert _ask(Decision(DecisionKind.MAL_ID, "MAL?"), "\n") is None


# --------------------------------------------------------------------------
# exit codes
# --------------------------------------------------------------------------
PICK = Decision(DecisionKind.SEARCH_RESULT, "Which?", options=("1", "2"))


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (WorkflowResult(JobState.COMPLETE, Stage.PROCESS), ExitCode.OK),
        (
            WorkflowResult(
                JobState.COMPLETE,
                Stage.PROCESS,
                outcomes={TrackerSelection.AITHER: TrackerRunOutcome.UPLOAD_FAILED},
            ),
            ExitCode.PARTIAL,
        ),
        (
            WorkflowResult(
                JobState.WAITING_FOR_INPUT, Stage.SEARCH, Path("j/abc"), decision=PICK
            ),
            ExitCode.WAITING,
        ),
        (
            WorkflowResult(
                JobState.FAILED, Stage.SEARCH, error="nobody", decision=PICK
            ),
            ExitCode.REFUSED,
        ),
        (WorkflowResult(JobState.FAILED, Stage.INPUT, error="gone"), ExitCode.FAILED),
    ],
)
def test_report_exit_codes(result: WorkflowResult, code: ExitCode) -> None:
    assert report(result, io.StringIO(), io.StringIO()) is code


def test_a_waiting_run_says_how_to_answer_it() -> None:
    err = io.StringIO()

    report(
        WorkflowResult(
            JobState.WAITING_FOR_INPUT, Stage.SEARCH, Path("jobs/abc"), decision=PICK
        ),
        io.StringIO(),
        err,
    )

    assert "nfoforge jobs answer abc VALUE" in err.getvalue()


# --------------------------------------------------------------------------
# commands, with the workflow stubbed
# --------------------------------------------------------------------------
class _Workflow:
    started: list[tuple[ReleaseRequest, dict]] = []
    resumed: list[tuple[Path, dict]] = []

    def __init__(self, _config: object, **_kwargs: object) -> None:
        pass

    def start(self, request: ReleaseRequest, answers: dict) -> WorkflowResult:
        _Workflow.started.append((request, answers))
        return WorkflowResult(JobState.COMPLETE, Stage.PROCESS)

    def resume(self, path: Path, answers: dict) -> WorkflowResult:
        _Workflow.resumed.append((path, answers))
        return WorkflowResult(JobState.COMPLETE, Stage.PROCESS)


@pytest.fixture
def stubbed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    config = SimpleNamespace(
        settings=SimpleNamespace(
            presets={"bhd": RunPreset(trackers=("BHD",), screenshot_count=6)},
            general=SimpleNamespace(working_dir=tmp_path),
        )
    )
    monkeypatch.setattr(cli_main, "load_config", lambda *_a, **_k: config)
    monkeypatch.setattr(cli_main, "Workflow", _Workflow)
    _Workflow.started, _Workflow.resumed = [], []
    return config


def _run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(["--no-input", *argv], out, err)
    return code, out.getvalue(), err.getvalue()


@pytest.mark.usefixtures("stubbed")
def test_upload_fills_from_the_preset_and_runs_unattended_without_a_terminal() -> None:
    code, _out, err = _run(
        "upload",
        "x.mkv",
        "--preset",
        "bhd",
        "--screenshots",
        "3",
        "--answer",
        "rename=yes",
    )

    request, answers = _Workflow.started[0]
    assert code == ExitCode.OK
    assert request.trackers == ("BHD",)
    assert request.screenshot_count == 3
    assert request.preset == "bhd"
    assert request.mode is AutomationMode.UNATTENDED
    assert answers == {"rename": True}
    assert "unattended" in err


@pytest.mark.usefixtures("stubbed")
def test_an_unknown_preset_is_an_error() -> None:
    code, _out, err = _run("upload", "x.mkv", "--preset", "nope")

    assert code == ExitCode.FAILED
    assert "no preset named 'nope'" in err


def test_jobs_answer_resumes_with_the_answer(
    stubbed: SimpleNamespace, tmp_path: Path
) -> None:
    from nfoforge.backend.jobs import build_job, save_job
    from nfoforge.backend.jobs.models import JobSummary

    job = build_job(name="Waiting", summary=JobSummary(), context={})
    job.state = JobState.WAITING_FOR_INPUT
    job.pending_decision = PICK.to_dict()
    path = save_job(job, tmp_path)

    code, out, _err = _run("jobs", "list", "--waiting")
    assert code == ExitCode.OK
    assert path.name in out

    code, out, _err = _run("jobs", "show", path.name[:6])
    assert "waiting on [search_result]" in out

    code, _out, _err = _run("jobs", "answer", path.name, "2")
    assert code == ExitCode.OK
    assert _Workflow.resumed == [(path, {"search_result": 2})]


@pytest.mark.usefixtures("stubbed")
def test_jobs_answer_needs_a_value_without_a_terminal(tmp_path: Path) -> None:
    from nfoforge.backend.jobs import build_job, save_job
    from nfoforge.backend.jobs.models import JobSummary

    job = build_job(name="Waiting", summary=JobSummary(), context={})
    job.pending_decision = PICK.to_dict()
    path = save_job(job, tmp_path)

    code, _out, err = _run("jobs", "answer", path.name)

    assert code == ExitCode.FAILED
    assert "nobody to ask" in err
