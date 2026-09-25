"""A headless run, end to end, against fake search, image and upload backends."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from pymediainfo import MediaInfo
import pytest

from nfoforge.backend.jobs import list_jobs, load_job
from nfoforge.backend.upload_retry import TrackerRunOutcome
from nfoforge.config.config import ConfigManager
from nfoforge.core.workflow.decisions import DecisionKind
from nfoforge.core.workflow.engine import Workflow
from nfoforge.core.workflow.events import CollectingSink, DecisionNeeded, StageStarted
from nfoforge.core.workflow.request import ReleaseRequest
from nfoforge.core.workflow.stages import Stage
from nfoforge.enums.automation import AutomationMode, JobState
from nfoforge.enums.tracker_selection import TrackerSelection
from tests.job_helpers import write_sample_media
from tests.repo_paths import build_app_paths

AITHER = TrackerSelection.AITHER


def _row(key: str, *, year: str = "2024") -> dict[str, Any]:
    return {
        "title": "The Movie",
        "year": year,
        "media_type": "movie",
        "tmdb_id": key,
        "imdb_id": "",
        "original_title": "The Movie",
        "genre_ids": [],
        "raw_data": {"id": int(key), "title": "The Movie", "original_language": "en"},
    }


class FakeSearch:
    timeout = 5

    def __init__(self, results: dict[str, dict[str, Any]]) -> None:
        self.results = results
        self.searched: list[str] = []

    def _parse_tmdb_api(self, query: str, _mode: object) -> dict[str, dict[str, Any]]:
        self.searched.append(query)
        return dict(self.results)

    def resolve_tmdb_reference(
        self, tmdb_id: str, _media_type: object, _mode: object
    ) -> dict[str, dict[str, Any]]:
        return {tmdb_id: _row(tmdb_id)}

    async def parse_other_ids(self, *_args: object) -> dict[str, Any]:
        return {}


class FakeProcess:
    def __init__(self, dupes: Sequence[str] = ()) -> None:
        self.dupes = list(dupes)
        self.skip_injection = False
        self.uploaded: list[str] = []

    async def dupe_checks(
        self, processing_queue: list[TrackerSelection], **_kwargs: object
    ) -> dict[TrackerSelection, tuple[TrackerSelection, bool, list[str]]]:
        return {
            tracker: (tracker, True, list(self.dupes)) for tracker in processing_queue
        }

    def unresolved_prompt_tokens(
        self, _trackers: object, answered: Mapping[str, str]
    ) -> list[str]:
        return [token for token in ("prompt_notes",) if token not in answered]

    def _seed_claim_overrides(self, _context: object) -> None:
        return None

    def process_trackers(self, **kwargs: Any) -> None:
        for name in kwargs["process_dict"]:
            self.uploaded.append(name)
            kwargs["run_outcome_cb"](TrackerSelection(name), TrackerRunOutcome.UPLOADED)


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConfigManager:
    monkeypatch.setattr(
        "nfoforge.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    manager = ConfigManager("test", build_app_paths(tmp_path / "config"))
    manager.settings.general.working_dir = tmp_path / "work"
    # the tracker checks have their own tests; these runs are about the engine
    monkeypatch.setattr(
        "nfoforge.core.workflow.steps.tracker_profile_problems", lambda *_a: []
    )
    monkeypatch.setattr(
        "nfoforge.core.workflow.steps.missing_nfo_templates", lambda *_a: []
    )
    return manager


@pytest.fixture
def movie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A release MediaInfo can read, named like a movie."""
    folder = tmp_path / "media"
    folder.mkdir()
    sample = write_sample_media(folder)
    release = sample.with_name("The.Movie.2024.1080p.BluRay.x264-GRP.mkv")
    sample.rename(release)

    class FakeMediaInput:
        def __init__(self, _signal: object) -> None:
            pass

        def get_media_info_files(
            self, files: list[Path]
        ) -> tuple[dict[Path, MediaInfo], dict[Path, str]]:
            return {
                path: cast(MediaInfo, MediaInfo.parse(path, legacy_stream_display=True))
                for path in files
            }, {}

    monkeypatch.setattr(
        "nfoforge.core.workflow.steps.MediaInputBackEnd", FakeMediaInput
    )
    return release


def _workflow(
    config: ConfigManager, search: FakeSearch, process: FakeProcess
) -> tuple[Workflow, CollectingSink]:
    sink = CollectingSink()
    return (
        Workflow(
            config,
            sink=sink,
            process_backend=cast(Any, process),
            search_backend=cast(Any, search),
        ),
        sink,
    )


def _request(movie: Path, **kwargs: Any) -> ReleaseRequest:
    base: dict[str, Any] = {
        "path": movie,
        "trackers": ("aither",),
        "mode": AutomationMode.UNATTENDED,
        "rename": False,
        "no_screenshots": True,
        "prompt_tokens": {"prompt_notes": "Encoded with care"},
    }
    return ReleaseRequest(**(base | kwargs))


def test_an_unattended_movie_run_uploads_and_is_archived(
    config: ConfigManager, movie: Path
) -> None:
    process = FakeProcess()
    workflow, sink = _workflow(config, FakeSearch({"42": _row("42")}), process)

    result = workflow.start(_request(movie))

    assert result.state is JobState.COMPLETE, result.error
    assert process.uploaded == [str(AITHER)]
    assert result.outcomes == {AITHER: TrackerRunOutcome.UPLOADED}
    assert [event.stage for event in sink.of(StageStarted)] == [
        "input",
        "search",
        "trackers",
        "pre_upload",
        "process",
    ]
    assert result.job_path is not None
    archive = load_job(result.job_path)
    assert archive.archived
    assert archive.state is JobState.COMPLETE
    assert archive.uploaded_trackers == [AITHER.name]


def test_an_ambiguous_search_is_refused_unattended_naming_the_way_out(
    config: ConfigManager, movie: Path
) -> None:
    remakes = {"1": _row("1"), "2": _row("2")}
    workflow, _sink = _workflow(config, FakeSearch(remakes), FakeProcess())

    result = workflow.start(_request(movie))

    assert result.state is JobState.FAILED
    assert result.stage is Stage.SEARCH
    assert result.decision is not None
    assert result.decision.kind is DecisionKind.SEARCH_RESULT
    assert "--tmdb-id" in (result.error or "")
    assert result.job_path is not None
    assert load_job(result.job_path).state is JobState.FAILED


def test_safe_mode_waits_then_resumes_with_the_answer(
    config: ConfigManager, movie: Path
) -> None:
    remakes = {"1": _row("1"), "2": _row("2")}
    process = FakeProcess()
    workflow, sink = _workflow(config, FakeSearch(remakes), process)

    waiting = workflow.start(_request(movie, mode=AutomationMode.SAFE))

    assert waiting.state is JobState.WAITING_FOR_INPUT
    assert waiting.job_path is not None
    assert sink.of(DecisionNeeded)
    listing = list_jobs([config.settings.general.working_dir])
    assert [job.state for job in listing] == [JobState.WAITING_FOR_INPUT]
    saved = load_job(waiting.job_path)
    assert saved.stage == "search"
    assert (saved.pending_decision or {})["id"] == "search_result"

    done = workflow.resume(waiting.job_path, {"search_result": "2"})

    assert done.state is JobState.COMPLETE, done.error
    assert process.uploaded == [str(AITHER)]
    assert load_job(done.job_path or waiting.job_path).state is JobState.COMPLETE


def test_an_interactive_run_asks(config: ConfigManager, movie: Path) -> None:
    asked: list[str] = []
    process = FakeProcess()
    workflow = Workflow(
        config,
        sink=CollectingSink(),
        ask=lambda decision: asked.append(decision.id) or "1",
        process_backend=cast(Any, process),
        search_backend=cast(Any, FakeSearch({"1": _row("1"), "2": _row("2")})),
    )

    result = workflow.start(_request(movie, mode=AutomationMode.INTERACTIVE))

    assert result.state is JobState.COMPLETE, result.error
    assert asked == ["search_result"]


def test_a_possible_dupe_stops_unattended_unless_skipped(
    config: ConfigManager, movie: Path
) -> None:
    process = FakeProcess(dupes=["The.Movie.2024.1080p-OTHER"])
    workflow, _sink = _workflow(config, FakeSearch({"42": _row("42")}), process)

    refused = workflow.start(_request(movie))
    assert refused.state is JobState.FAILED
    assert refused.decision is not None
    assert refused.decision.id == "dupes_found:AITHER"
    assert process.uploaded == []

    skipped = workflow.start(_request(movie, skip_dupe_check=True))
    assert skipped.state is JobState.COMPLETE, skipped.error
    assert process.uploaded == [str(AITHER)]


def test_an_unanswered_prompt_token_is_a_decision(
    config: ConfigManager, movie: Path
) -> None:
    workflow, _sink = _workflow(config, FakeSearch({"42": _row("42")}), FakeProcess())

    result = workflow.start(_request(movie, prompt_tokens={}))

    assert result.state is JobState.FAILED
    assert result.decision is not None
    assert result.decision.kind is DecisionKind.PROMPT_TOKENS


@pytest.fixture
def rendered_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sample release is audio only, which the name renderer rejects."""
    monkeypatch.setattr(
        "nfoforge.core.workflow.steps.render_movie_name",
        lambda *_args: Path("The.Movie.2024.mkv"),
    )


@pytest.mark.usefixtures("rendered_name")
def test_a_dry_run_changes_nothing(config: ConfigManager, movie: Path) -> None:
    process = FakeProcess()
    workflow, _sink = _workflow(config, FakeSearch({"42": _row("42")}), process)

    result = workflow.start(_request(movie, dry_run=True, rename=True))

    assert result.state is JobState.COMPLETE, result.error
    assert process.uploaded == []
    assert movie.exists()
    assert result.job_path is None
    assert list_jobs([config.settings.general.working_dir]) == []


@pytest.mark.usefixtures("rendered_name")
def test_a_confirmed_rename_moves_the_release(
    config: ConfigManager, movie: Path
) -> None:
    workflow, _sink = _workflow(config, FakeSearch({"42": _row("42")}), FakeProcess())

    result = workflow.start(_request(movie, rename=True))

    assert result.state is JobState.COMPLETE, result.error
    assert not movie.exists()
    assert (movie.parent / "The.Movie.2024.mkv").is_file()


def test_missing_input_fails_without_a_job(
    config: ConfigManager, tmp_path: Path
) -> None:
    workflow, _sink = _workflow(config, FakeSearch({}), FakeProcess())

    result = workflow.start(_request(tmp_path / "nowhere.mkv"))

    assert result.state is JobState.FAILED
    assert result.stage is Stage.INPUT
    assert result.job_path is None


def test_an_unknown_tracker_fails(config: ConfigManager, movie: Path) -> None:
    workflow, _sink = _workflow(config, FakeSearch({"42": _row("42")}), FakeProcess())

    result = workflow.start(_request(movie, trackers=("nope",)))

    assert result.state is JobState.FAILED
    assert result.stage is Stage.TRACKERS
    assert "nope" in (result.error or "")


def test_a_desktop_job_cannot_be_resumed_headlessly(
    config: ConfigManager, movie: Path, tmp_path: Path
) -> None:
    from nfoforge.backend.jobs import build_job, save_job
    from nfoforge.backend.jobs.models import JobSummary

    path = save_job(build_job(name="GUI", summary=JobSummary(), context={}), tmp_path)
    workflow, _sink = _workflow(config, FakeSearch({}), FakeProcess())

    result = workflow.resume(path)

    assert result.state is JobState.FAILED
    assert "Open it in NfoForge" in (result.error or "")


class SeriesSearch(FakeSearch):
    def resolve_tmdb_reference(
        self, _tmdb_id: str, _media_type: object, _mode: object
    ) -> dict[str, dict[str, Any]]:
        return dict(self.results)

    async def parse_other_ids(self, *_args: object) -> dict[str, Any]:
        episodes = [
            {"seasonNumber": 1, "number": 1, "name": "Pilot"},
            {"seasonNumber": 1, "number": 2, "name": "Second"},
        ]
        return {
            "tvdb_data": {
                "success": True,
                "result": {
                    "id": 77,
                    "episodes_by_type": {
                        1: {
                            "type": "default",
                            "type_name": "Aired",
                            "episodes": episodes,
                        }
                    },
                },
            }
        }


def _series_row() -> dict[str, Any]:
    row = _row("9")
    row["media_type"] = "tv"
    row["raw_data"] = {"id": 9, "name": "The Movie", "original_language": "en"}
    return row


@pytest.fixture
def pack(movie: Path) -> Path:
    """Two episodes in a folder; the second's name carries no numbering."""
    folder = movie.parent / "The.Movie.S01"
    folder.mkdir()
    first = folder / "The.Movie.S01E01.1080p.WEB-DL-GRP.mkv"
    movie.rename(first)
    (folder / "Unnumbered.mkv").write_bytes(first.read_bytes())
    return folder


def test_a_series_run_matches_episodes_and_asks_about_the_rest(
    config: ConfigManager, pack: Path
) -> None:
    process = FakeProcess()
    workflow, _sink = _workflow(config, SeriesSearch({"9": _series_row()}), process)

    stopped = workflow.start(_request(pack, tmdb_id="9"))

    assert stopped.state is JobState.FAILED
    assert stopped.stage is Stage.SERIES_MATCH
    assert stopped.decision is not None
    assert stopped.decision.kind is DecisionKind.EPISODE_MAPPING
    assert stopped.decision.context["files"] == ["Unnumbered.mkv"]

    done = workflow.start(
        _request(pack, tmdb_id="9"),
        answers={"episode_mapping": {"Unnumbered.mkv": {"season": 1, "episode": 2}}},
    )

    assert done.state is JobState.COMPLETE, done.error
    assert process.uploaded == [str(AITHER)]
