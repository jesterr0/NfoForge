"""Whether a profile is ready to upload, checked without uploading anything.

A problem is something that will stop a run: a tracker with no template, an
image host switched on with no credentials, a preset naming a tracker that does
not exist. A warning is something worth a look that may be deliberate: an
empty credential on a tracker that may not need it, a tool that is not set.

Reports every finding at once, like the upload preflight, rather than the
first one a run would trip over.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nfoforge.backend.template_selector import TemplateSelectorBackEnd
from nfoforge.core.trackers.image_hosts import available_image_hosts, find_image_host
from nfoforge.core.trackers.validate import (
    missing_nfo_templates,
    resolve_tracker_names,
    tracker_profile_problems,
)
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.utils.secret_redaction import CREDENTIAL_FIELD_NAMES

if TYPE_CHECKING:
    from nfoforge.config.config import ConfigManager

OPTIONAL_CREDENTIALS = frozenset({"alt_2_fa_token", "totp", "rss_key"})
"""Credential fields a tracker works without: two-factor seeds and RSS keys."""


class Severity(StrEnum):
    PROBLEM = "problem"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    subject: str
    """What it is about: a tracker, an image host, a preset, a tool."""
    message: str

    def __str__(self) -> str:
        return f"{self.subject}: {self.message}"


def check_profile(
    config: ConfigManager,
    trackers: Sequence[str] | None = None,
    template_selector: TemplateSelectorBackEnd | None = None,
) -> list[Finding]:
    """Every finding for the loaded profile.

    `trackers` names the trackers to check. Left out, the trackers the presets
    name are checked, and every tracker with a credential filled in -- the ones
    this profile looks set up to upload to.
    """
    settings = config.settings
    selector = template_selector or TemplateSelectorBackEnd()
    findings: list[Finding] = []

    if not settings.api_keys.tmdb_api_key:
        findings.append(
            Finding(
                Severity.PROBLEM,
                "TMDB",
                "no API key is set, and every run searches TMDB",
            )
        )
    findings += _tool_findings(settings.dependencies)
    findings += _working_dir_findings(Path(settings.general.working_dir))
    findings += _image_host_findings(settings)
    findings += _preset_findings(config)
    findings += _tracker_findings(settings, trackers, selector)
    return findings


# --------------------------------------------------------------------------
# tools and folders
# --------------------------------------------------------------------------
def _tool_findings(dependencies: Any) -> list[Finding]:
    findings: list[Finding] = []
    tools: dict[str, tuple[Path | None, str | None]] = {
        "FFmpeg": (dependencies.ffmpeg, "screenshots cannot be generated"),
        "FFprobe": (dependencies.ffprobe, None),
        "FrameForge": (dependencies.frame_forge, None),
        "mkbrr": (
            dependencies.mkbrr,
            "torrents are set to be built with it"
            if dependencies.enable_mkbrr
            else None,
        ),
    }
    for name, (path, needed_for) in tools.items():
        if path is None or not str(path):
            if needed_for:
                findings.append(
                    Finding(Severity.WARNING, name, f"not set, so {needed_for}")
                )
        elif not Path(path).is_file():
            findings.append(
                Finding(Severity.PROBLEM, name, f"set to {path}, which does not exist")
            )
    return findings


def _working_dir_findings(working_dir: Path) -> list[Finding]:
    if working_dir.exists() and not working_dir.is_dir():
        return [
            Finding(
                Severity.PROBLEM,
                "Working directory",
                f"{working_dir} is a file, not a folder",
            )
        ]
    return []


# --------------------------------------------------------------------------
# image hosts and presets
# --------------------------------------------------------------------------
def _image_host_findings(settings: Any) -> list[Finding]:
    return [
        Finding(
            Severity.PROBLEM,
            str(host),
            "the image host is switched on but not fully configured",
        )
        for host, payload in settings.image_hosts.by_selection().items()
        if payload.enabled and not payload.is_configured()
    ]


def _preset_findings(config: ConfigManager) -> list[Finding]:
    settings = config.settings
    tracker_map = settings.trackers.by_selection()
    available = available_image_hosts(settings, config.plugin_manager)
    findings: list[Finding] = []
    for name, preset in settings.presets.items():
        subject = f"Preset {name!r}"
        _, unknown = resolve_tracker_names(preset.trackers, tracker_map)
        if unknown:
            findings.append(
                Finding(
                    Severity.PROBLEM,
                    subject,
                    f"names unknown tracker(s): {', '.join(unknown)}",
                )
            )
        if preset.image_host is not None:
            try:
                find_image_host(preset.image_host, available)
            except ValueError as error:
                findings.append(Finding(Severity.PROBLEM, subject, str(error)))
    return findings


# --------------------------------------------------------------------------
# trackers
# --------------------------------------------------------------------------
def _credentials(info: object) -> dict[str, str]:
    """A tracker's credential fields and their values, "" for unset."""
    return {
        item.name: str(getattr(info, item.name) or "")
        for item in fields(info)  # type: ignore[arg-type]
        if item.name.casefold() in CREDENTIAL_FIELD_NAMES
    }


def trackers_to_check(
    settings: Any, named: Sequence[str] | None
) -> tuple[list[TrackerSelection], list[str]]:
    """The trackers a check covers, and any names that matched none."""
    tracker_map: Mapping[TrackerSelection, Any] = settings.trackers.by_selection()
    order = settings.trackers.order
    if named:
        return resolve_tracker_names(named, tracker_map, order)
    from_presets = [
        name for preset in settings.presets.values() for name in preset.trackers
    ]
    with_credentials = [
        tracker.name
        for tracker, info in tracker_map.items()
        if any(_credentials(info).values())
    ]
    chosen, _unknown = resolve_tracker_names(
        [*from_presets, *with_credentials], tracker_map, order
    )
    return chosen, []


def _tracker_findings(
    settings: Any,
    named: Sequence[str] | None,
    template_selector: TemplateSelectorBackEnd,
) -> list[Finding]:
    tracker_map = settings.trackers.by_selection()
    trackers, unknown = trackers_to_check(settings, named)
    findings: list[Finding] = []
    if unknown:
        known = ", ".join(sorted(tracker.name for tracker in tracker_map))
        findings.append(
            Finding(
                Severity.PROBLEM,
                "Trackers",
                f"unknown tracker(s): {', '.join(unknown)} (known: {known})",
            )
        )
    if not trackers and not unknown:
        findings.append(
            Finding(
                Severity.WARNING,
                "Trackers",
                "none has a credential set yet, so there is nothing to upload to",
            )
        )
        return findings

    for problem in tracker_profile_problems(trackers, tracker_map, template_selector):
        subject, _, message = problem.partition(": ")
        findings.append(Finding(Severity.PROBLEM, subject, message))
    findings += [
        Finding(Severity.PROBLEM, str(tracker), "no NFO template is assigned")
        for tracker in missing_nfo_templates(trackers, tracker_map)
    ]
    findings += _empty_credentials(trackers, tracker_map)
    return findings


def _empty_credentials(
    trackers: Iterable[TrackerSelection], tracker_map: Mapping[TrackerSelection, Any]
) -> list[Finding]:
    findings: list[Finding] = []
    for tracker in trackers:
        empty = [
            name
            for name, value in _credentials(tracker_map[tracker]).items()
            if not value and name not in OPTIONAL_CREDENTIALS
        ]
        if empty:
            findings.append(
                Finding(
                    Severity.WARNING,
                    str(tracker),
                    f"empty: {', '.join(empty)} (fine if this tracker does not "
                    f"need {'it' if len(empty) == 1 else 'them'})",
                )
            )
    return findings
