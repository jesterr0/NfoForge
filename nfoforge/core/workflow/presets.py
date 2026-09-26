"""Filling a run's request from a named preset.

The order is: what the run was given, then the preset, then the profile. A
value given for the run always wins; the preset fills what the run left open;
anything both leave open is worked out from the profile as usual. Token
tables merge, with the run's entries winning over the preset's.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from typing import TYPE_CHECKING, Any

from nfoforge.config.presets import RunPreset
from nfoforge.core.workflow.request import ReleaseRequest

if TYPE_CHECKING:
    from nfoforge.config.models import AppConfig

_MERGED = {"token_overrides", "prompt_tokens"}


class PresetError(LookupError):
    """A preset was named that the profile does not have."""


def find_preset(settings: AppConfig, name: str) -> RunPreset:
    try:
        return settings.presets[name]
    except KeyError:
        known = ", ".join(sorted(settings.presets)) or "none are defined"
        raise PresetError(
            f"This profile has no preset named {name!r} ({known})"
        ) from None


def _preset_values(preset: RunPreset) -> dict[str, Any]:
    """The answers a preset actually gives; unset ones are left out."""
    values: dict[str, Any] = {}
    for item in fields(RunPreset):
        value = getattr(preset, item.name)
        if value is None or (isinstance(value, tuple | dict) and not value):
            continue
        values[item.name] = value
    return values


def build_request(
    given: Mapping[str, Any],
    preset: RunPreset | None = None,
    *,
    preset_name: str | None = None,
) -> ReleaseRequest:
    """A request from what the run was `given`, filled in from `preset`.

    `given` holds only what the run was explicitly told: a key that is absent,
    or `None`, is open for the preset to fill. It must include `path`.
    """
    explicit = {key: value for key, value in given.items() if value is not None}
    values = _preset_values(preset) if preset else {}
    for key, value in explicit.items():
        if key in _MERGED:
            values[key] = dict(values.get(key) or {}) | dict(value)
        else:
            values[key] = value
    if preset_name is not None:
        values["preset"] = preset_name
    if "path" not in values:
        raise ValueError("A release request needs a path")
    known = {item.name for item in fields(ReleaseRequest)}
    return ReleaseRequest(
        **{key: value for key, value in values.items() if key in known}
    )
