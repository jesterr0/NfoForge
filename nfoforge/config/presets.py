"""Named run presets, kept in a config profile.

A preset is a set of answers a run would otherwise be given one by one --
which trackers, which image host, how many screenshots -- saved under a name:

    [presets.bhd-encode]
    trackers = ["BHD"]
    image_host = "Pixhost"
    screenshot_count = 6

It fills in a run's request and nothing else. The profile's settings are not
changed by one, and an answer given for the run itself wins over the preset's.

Presets are written by hand for now. Nothing in the desktop app edits them,
and saving a profile from the app keeps them exactly as written.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any

from nfoforge.enums.automation import AutomationMode
from nfoforge.exceptions import ConfigError


@dataclass(frozen=True, slots=True)
class RunPreset:
    """Answers for a run, by name. `None` leaves the question to the profile."""

    trackers: tuple[str, ...] = ()
    image_host: str | None = None
    """An image host by name, e.g. "Pixhost", or "Disabled" for none."""
    screenshot_count: int | None = None
    no_screenshots: bool | None = None
    rename: bool | None = None
    filename_token: str | None = None
    mode: AutomationMode | None = None
    skip_dupe_check: bool | None = None
    no_inject: bool | None = None
    token_overrides: dict[str, str] = field(default_factory=dict)
    prompt_tokens: dict[str, str] = field(default_factory=dict)


_STRINGS = {"image_host", "filename_token"}
_INTS = {"screenshot_count"}
_BOOLS = {"no_screenshots", "rename", "skip_dupe_check", "no_inject"}
_TABLES = {"token_overrides", "prompt_tokens"}


def _parse_one(name: str, table: object) -> RunPreset:
    where = f"presets.{name}"
    if not isinstance(table, Mapping):
        raise ConfigError(f"Expected table at {where}")

    known = {item.name for item in fields(RunPreset)}
    unknown = sorted(set(table) - known)
    if unknown:
        raise ConfigError(
            f"Unknown key(s) at {where}: {', '.join(unknown)}. "
            f"A preset may set: {', '.join(sorted(known))}"
        )

    values: dict[str, Any] = {}
    for key, raw in table.items():
        value = raw.unwrap() if hasattr(raw, "unwrap") else raw
        path = f"{where}.{key}"
        if key == "trackers":
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise ConfigError(f"Expected a list of tracker names at {path}")
            values[key] = tuple(value)
        elif key == "mode":
            try:
                values[key] = AutomationMode(str(value).lower())
            except ValueError as error:
                choices = ", ".join(str(mode) for mode in AutomationMode)
                raise ConfigError(f"{path} must be one of: {choices}") from error
        elif key in _STRINGS:
            if not isinstance(value, str):
                raise ConfigError(f"Expected a string at {path}")
            values[key] = value
        elif key in _INTS:
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ConfigError(f"Expected a positive whole number at {path}")
            values[key] = value
        elif key in _BOOLS:
            if not isinstance(value, bool):
                raise ConfigError(f"Expected true or false at {path}")
            values[key] = value
        elif key in _TABLES:
            if not isinstance(value, Mapping) or not all(
                isinstance(item, str) for item in value.values()
            ):
                raise ConfigError(f"Expected a table of strings at {path}")
            values[key] = {str(k): str(v) for k, v in value.items()}
    return RunPreset(**values)


def parse_presets(document: object) -> dict[str, RunPreset]:
    """Every preset in a profile's `[presets]` table. Absent means none."""
    if document is None:
        return {}
    if not isinstance(document, Mapping):
        raise ConfigError("Expected table at presets")
    return {str(name): _parse_one(str(name), table) for name, table in document.items()}
