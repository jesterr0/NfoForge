"""What one run was asked to do.

Every interface -- the desktop app, the command line, a future server --
describes a run as a `ReleaseRequest`. Each field other than `path` is an
answer given in advance to a question the run would otherwise have to ask or
work out, so an empty field means "work it out", never "none".

A request is recorded in the job it starts, as JSON, so a job that stops for
input resumes with the same instructions it began with.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from nfoforge.enums.automation import AutomationMode


@dataclass(frozen=True, slots=True)
class ReleaseRequest:
    path: Path
    """The file or folder being released."""

    trackers: tuple[str, ...] = ()
    """Trackers to upload to. Never inferred from the profile when empty."""

    mode: AutomationMode = AutomationMode.INTERACTIVE

    tmdb_id: str | None = None
    imdb_id: str | None = None
    tvdb_id: str | None = None
    """Identify the release directly instead of searching by title."""

    season: int | None = None
    episode: int | None = None
    """Numbering for a release whose filenames do not carry it."""

    rename: bool | None = None
    """Force renaming on or off. None follows the profile."""

    filename_token: str | None = None
    """Template the rename renders with, instead of the profile's."""

    token_overrides: dict[str, str] = field(default_factory=dict)
    """Forced values for file/title tokens, over what the filenames claim."""

    prompt_tokens: dict[str, str] = field(default_factory=dict)
    """Answers to the `prompt_*` tokens an NFO template asks for."""

    screenshot_count: int | None = None
    """How many screenshots to generate, instead of the profile's count."""

    screenshot_dir: Path | None = None
    """Screenshots chosen beforehand, instead of generating any."""

    image_host: str | None = None
    """Where every tracker's screenshots go, by name ("Pixhost", "Disabled").
    None uses each tracker's last-used host, as the desktop app does."""

    no_screenshots: bool = False

    skip_dupe_check: bool = False
    """Upload without asking the trackers whether they already have this."""

    no_inject: bool = False
    """Upload without handing the torrent to any configured client."""

    dry_run: bool = False
    """Resolve and report everything, then stop before changing anything."""

    preset: str | None = None
    """The profile preset this request was filled from, for the record."""

    def to_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, Path):
                value = str(value)
            elif isinstance(value, tuple):
                value = list(value)
            elif isinstance(value, dict):
                value = dict(value)
            document[item.name] = value
        return document

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> ReleaseRequest:
        """Rebuild a request. Unknown keys are ignored, missing ones defaulted."""
        known = {item.name for item in fields(cls)}
        values = {key: value for key, value in document.items() if key in known}
        if "path" not in values:
            raise ValueError("A release request needs a path")
        values["path"] = Path(values["path"])
        if values.get("screenshot_dir") is not None:
            values["screenshot_dir"] = Path(values["screenshot_dir"])
        if "trackers" in values:
            values["trackers"] = tuple(str(tracker) for tracker in values["trackers"])
        if "mode" in values:
            values["mode"] = AutomationMode(values["mode"])
        return cls(**values)
