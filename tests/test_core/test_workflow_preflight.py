"""The checks a headless run makes before it does any work."""

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest

from nfoforge.config.config import ConfigManager
from nfoforge.core.workflow.preflight import preflight_problems
from nfoforge.core.workflow.request import ReleaseRequest
from nfoforge.enums.automation import AutomationMode
from nfoforge.enums.tracker_selection import TrackerSelection
from tests.repo_paths import build_app_paths

AITHER = TrackerSelection.AITHER


class FakeTemplates:
    def load_templates(self) -> dict[str, str]:
        return {"movie": ""}


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConfigManager:
    monkeypatch.setattr(
        "nfoforge.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    manager = ConfigManager("test", build_app_paths(tmp_path / "config"))
    manager.settings.api_keys.tmdb_api_key = "key"
    aither = manager.settings.trackers.by_selection()[AITHER]
    aither.upload_enabled = True
    aither.nfo_template = "movie"
    return manager


@pytest.fixture
def release(tmp_path: Path) -> Path:
    path = tmp_path / "The.Movie.2024.1080p.BluRay.x264-GRP.mkv"
    path.write_bytes(b"")
    return path


def _no_prompts(_trackers: Iterable[TrackerSelection], _answered: object) -> list[str]:
    return []


def _problems(
    config: ConfigManager,
    request: ReleaseRequest,
    *,
    screenshots: bool = False,
    answers: Mapping[str, Any] | None = None,
    prompts: Any = _no_prompts,
) -> list[str]:
    return preflight_problems(
        request,
        config,
        screenshots=screenshots,
        answers=answers or {},
        unresolved_prompt_tokens=prompts,
        template_selector=FakeTemplates(),  # type: ignore[arg-type]
    )


def _request(path: Path, **kwargs: Any) -> ReleaseRequest:
    return ReleaseRequest(
        **(
            {"path": path, "trackers": ("aither",), "mode": AutomationMode.UNATTENDED}
            | kwargs
        )
    )


def test_a_sound_request_has_no_problems(config: ConfigManager, release: Path) -> None:
    assert _problems(config, _request(release)) == []


def test_every_problem_is_reported_at_once(
    config: ConfigManager, tmp_path: Path
) -> None:
    config.settings.api_keys.tmdb_api_key = ""

    problems = _problems(
        config,
        _request(
            tmp_path / "missing.mkv",
            trackers=(),
            image_host="NoSuchHost",
        ),
        screenshots=True,
    )

    assert len(problems) == 4
    assert "missing.mkv" in problems[0]
    assert "TMDB API key" in problems[1]
    assert "--trackers" in problems[2]
    assert "NoSuchHost" in problems[3]


def test_unknown_trackers_are_named_with_the_known_ones(
    config: ConfigManager, release: Path
) -> None:
    (problem,) = _problems(config, _request(release, trackers=("aither", "nope")))

    assert "nope" in problem
    assert "AITHER" in problem


def test_a_tracker_the_profile_cannot_serve_is_reported(
    config: ConfigManager, release: Path
) -> None:
    aither = config.settings.trackers.by_selection()[AITHER]
    aither.upload_enabled = False
    aither.nfo_template = ""

    problems = _problems(config, _request(release))

    assert any("uploads are disabled" in problem for problem in problems)
    assert any("no NFO template" in problem for problem in problems)


def test_screenshot_options_matter_only_when_screenshots_are_taken(
    config: ConfigManager, release: Path, tmp_path: Path
) -> None:
    request = _request(
        release, image_host="NoSuchHost", screenshot_dir=tmp_path / "shots"
    )

    assert _problems(config, request, screenshots=False) == []
    problems = _problems(config, request, screenshots=True)
    assert any("Screenshot folder does not exist" in p for p in problems)
    assert any("NoSuchHost" in p for p in problems)


def test_an_empty_screenshot_folder_is_reported(
    config: ConfigManager, release: Path, tmp_path: Path
) -> None:
    folder = tmp_path / "shots"
    folder.mkdir()

    (problem,) = _problems(
        config, _request(release, screenshot_dir=folder), screenshots=True
    )

    assert "No images found" in problem


def test_disabled_is_always_an_available_image_host(
    config: ConfigManager, release: Path
) -> None:
    request = _request(release, image_host="Disabled")

    assert _problems(config, request, screenshots=True) == []


def test_unanswered_prompt_tokens_refuse_only_an_unattended_run(
    config: ConfigManager, release: Path
) -> None:
    def prompts(_trackers: object, answered: Mapping[str, str]) -> list[str]:
        return [token for token in ("prompt_notes",) if token not in answered]

    (problem,) = _problems(config, _request(release), prompts=prompts)
    assert "prompt_notes" in problem

    answered = _request(release, prompt_tokens={"prompt_notes": "x"})
    assert _problems(config, answered, prompts=prompts) == []
    assert (
        _problems(
            config,
            _request(release),
            prompts=prompts,
            answers={"prompt_tokens": {"prompt_notes": "x"}},
        )
        == []
    )
    for mode in (AutomationMode.INTERACTIVE, AutomationMode.SAFE):
        assert _problems(config, _request(release, mode=mode), prompts=prompts) == []
