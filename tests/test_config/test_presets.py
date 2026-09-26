"""Run presets kept in a config profile."""

from pathlib import Path

import pytest
import tomlkit

from nfoforge.config.config import ConfigManager
from nfoforge.config.presets import RunPreset, parse_presets
from nfoforge.enums.automation import AutomationMode
from nfoforge.exceptions import ConfigError
from tests.test_config.config_tree import build_config_paths

PRESETS = """
[presets.bhd-encode]
trackers = ["BHD"]
image_host = "Pixhost"
screenshot_count = 6
rename = true
mode = "unattended"
token_overrides = { edition = "Directors Cut" }

[presets.quick]
no_screenshots = true
"""


def test_presets_are_parsed() -> None:
    presets = parse_presets(tomlkit.parse(PRESETS)["presets"])

    assert presets["bhd-encode"] == RunPreset(
        trackers=("BHD",),
        image_host="Pixhost",
        screenshot_count=6,
        rename=True,
        mode=AutomationMode.UNATTENDED,
        token_overrides={"edition": "Directors Cut"},
    )
    assert presets["quick"] == RunPreset(no_screenshots=True)


def test_no_presets_table_means_none() -> None:
    assert parse_presets(None) == {}


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ({"x": {"trakers": ["BHD"]}}, "Unknown key"),
        ({"x": {"trackers": "BHD"}}, "list of tracker names"),
        ({"x": {"screenshot_count": 0}}, "positive whole number"),
        ({"x": {"screenshot_count": True}}, "positive whole number"),
        ({"x": {"rename": "yes"}}, "true or false"),
        ({"x": {"mode": "yolo"}}, "must be one of"),
        ({"x": "not a table"}, "Expected table"),
    ],
)
def test_bad_presets_name_the_problem(table: dict, message: str) -> None:
    with pytest.raises(ConfigError, match=message) as error:
        parse_presets(table)
    assert "presets.x" in str(error.value)


def test_a_profile_keeps_its_presets_through_a_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "nfoforge.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = build_config_paths(tmp_path)
    ConfigManager("test", paths)
    profile = paths.user_configs / "test.toml"
    profile.write_text(profile.read_text(encoding="utf-8") + PRESETS, encoding="utf-8")

    manager = ConfigManager("test", paths)
    assert manager.settings.presets["bhd-encode"].screenshot_count == 6

    manager.save()
    reloaded = ConfigManager("test", paths)

    assert reloaded.settings.presets == manager.settings.presets
    assert "[presets.bhd-encode]" in profile.read_text(encoding="utf-8")
