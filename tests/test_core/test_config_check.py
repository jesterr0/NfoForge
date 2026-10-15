"""Whether a profile is ready to upload, checked without uploading."""

from pathlib import Path

import pytest

from nfoforge.config.config import ConfigManager
from nfoforge.config.presets import RunPreset
from nfoforge.core.config_check import Finding, Severity, check_profile
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.payloads.image_hosts import ImageBBPayload
from tests.repo_paths import build_app_paths

AITHER = TrackerSelection.AITHER
TL = TrackerSelection.TORRENT_LEECH


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
    return manager


def _ready(config: ConfigManager, tracker: TrackerSelection = AITHER) -> None:
    info = config.settings.trackers.by_selection()[tracker]
    info.upload_enabled = True
    info.nfo_template = "movie"
    info.announce_url = "https://tracker.example/announce/abc"
    info.api_key = "secret"  # type: ignore[attr-defined]


def _check(config: ConfigManager, trackers: list[str] | None = None) -> list[Finding]:
    return check_profile(config, trackers, template_selector=FakeTemplates())  # type: ignore[arg-type]


def _problems(findings: list[Finding]) -> list[str]:
    return [str(f) for f in findings if f.severity is Severity.PROBLEM]


def _warnings(findings: list[Finding]) -> list[str]:
    return [str(f) for f in findings if f.severity is Severity.WARNING]


def test_a_ready_profile_has_no_problems(config: ConfigManager) -> None:
    _ready(config)

    assert _problems(_check(config)) == []


def test_a_missing_tmdb_key_is_a_problem(config: ConfigManager) -> None:
    config.settings.api_keys.tmdb_api_key = ""

    assert any("TMDB" in problem for problem in _problems(_check(config)))


def test_a_profile_with_no_credentials_says_there_is_nothing_to_upload_to(
    config: ConfigManager,
) -> None:
    findings = _check(config)

    assert any("none has a credential" in warning for warning in _warnings(findings))


def test_a_tracker_with_credentials_is_checked_for_its_template(
    config: ConfigManager,
) -> None:
    _ready(config)
    config.settings.trackers.by_selection()[AITHER].nfo_template = ""

    assert _problems(_check(config)) == [f"{AITHER}: no NFO template is assigned"]


def test_empty_credentials_are_warnings_and_optional_ones_are_not_named(
    config: ConfigManager,
) -> None:
    tl = config.settings.trackers.by_selection()[TL]
    tl.nfo_template = "movie"
    tl.username = "me"  # type: ignore[attr-defined]

    warnings = [w for w in _warnings(_check(config)) if w.startswith(str(TL))]

    assert len(warnings) == 1
    assert "password" in warnings[0]
    assert "alt_2_fa_token" not in warnings[0]


def test_named_trackers_are_checked_even_without_credentials(
    config: ConfigManager,
) -> None:
    problems = _problems(_check(config, ["aither", "nope"]))

    assert any("nope" in problem for problem in problems)
    assert f"{AITHER}: no NFO template is assigned" in problems


def test_presets_naming_what_does_not_exist_are_problems(
    config: ConfigManager,
) -> None:
    _ready(config)
    config.settings.presets["bad"] = RunPreset(
        trackers=("aither", "nope"), image_host="NoSuchHost"
    )

    problems = [p for p in _problems(_check(config)) if p.startswith("Preset")]

    assert any("nope" in problem for problem in problems)
    assert any("NoSuchHost" in problem for problem in problems)


def test_an_image_host_switched_on_without_credentials_is_a_problem(
    config: ConfigManager,
) -> None:
    _ready(config)
    host = next(
        payload
        for payload in config.settings.image_hosts.by_selection().values()
        if isinstance(payload, ImageBBPayload)
    )
    host.enabled = True
    host.api_key = ""

    assert any("not fully configured" in p for p in _problems(_check(config)))


def test_a_tool_set_to_a_missing_file_is_a_problem(
    config: ConfigManager, tmp_path: Path
) -> None:
    _ready(config)
    config.settings.dependencies.ffmpeg = tmp_path / "ffmpeg.exe"

    assert any(p.startswith("FFmpeg") for p in _problems(_check(config)))
