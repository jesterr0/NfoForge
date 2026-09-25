"""The questions a run can hit, and who answers them.

NfoForge deliberately leaves some calls to a person: which search result is
the release, whether to upload past a possible duplicate, what goes in a
template's prompt tokens. A run raises each one as a `Decision` and hands it to
a `DecisionPolicy`, which is where the interfaces differ:

- `InteractivePolicy` asks someone -- a dialog, a terminal prompt -- and waits.
- `SafePolicy` stops the run. The job is kept, waiting for input, and resumes
  where it stopped once the question is answered.
- `UnattendedPolicy` fails the run, naming how to answer it in advance.

All three take answers given beforehand (the request's IDs, answers supplied on
resume), keyed by `Decision.id`, and use them before doing anything else. No
policy guesses: a run that nobody answered stops rather than picking for
itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Protocol

from nfoforge.enums.automation import AutomationMode


class DecisionKind(StrEnum):
    SEARCH_RESULT = "search_result"
    """Which search result is this release."""
    MAL_ID = "mal_id"
    """AniList knows the release but not its MyAnimeList ID."""
    CONTINUE_WITHOUT_TVDB = "continue_without_tvdb"
    """TVDB failed; go on and map episodes by hand?"""
    EPISODE_MAPPING = "episode_mapping"
    """Files that could not be matched to an episode."""
    RENAME = "rename"
    """Confirm the files and folders a rename moves."""
    MULTI_SEASON_PACK = "multi_season_pack"
    """A multi-season pack would be filed under one season on some trackers."""
    SCREENSHOTS = "screenshots"
    """Continue without screenshots, or confirm the selection."""
    PROMPT_TOKENS = "prompt_tokens"
    """Values for the `prompt_*` tokens an NFO template asks for."""
    OVERVIEW = "overview"
    """Review or edit the titles and NFOs before upload."""
    DUPES_FOUND = "dupes_found"
    """A tracker may already have this release."""
    DUPE_CHECK_FAILED = "dupe_check_failed"
    """A tracker could not be asked whether it has this release."""
    TORRENT_OVERWRITE = "torrent_overwrite"
    UPLOAD_RETRY = "upload_retry"
    IMAGE_RETRY = "image_retry"
    TWO_FACTOR = "two_factor"


@dataclass(frozen=True, slots=True)
class Decision:
    kind: DecisionKind
    prompt: str
    """The question, as a person would read it."""
    subject: str = ""
    """What it is about, when a run can ask the same kind twice (a tracker)."""
    options: tuple[str, ...] = ()
    """The acceptable answers, when they are a fixed set."""
    default: Any = None
    """What an interactive prompt pre-selects. Never taken on its own."""
    hint: str = ""
    """How to answer it in advance, e.g. "pass --tmdb-id"."""
    context: dict[str, Any] = field(default_factory=dict)
    """JSON-able details a person needs to answer it."""

    @property
    def id(self) -> str:
        """Stable across a stop and a resume, so an answer finds its question."""
        return f"{self.kind}:{self.subject}" if self.subject else str(self.kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": str(self.kind),
            "prompt": self.prompt,
            "subject": self.subject,
            "options": list(self.options),
            "default": self.default,
            "hint": self.hint,
            "context": dict(self.context),
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> Decision:
        return cls(
            kind=DecisionKind(document["kind"]),
            prompt=str(document.get("prompt", "")),
            subject=str(document.get("subject", "")),
            options=tuple(str(option) for option in document.get("options", ())),
            default=document.get("default"),
            hint=str(document.get("hint", "")),
            context=dict(document.get("context") or {}),
        )


@dataclass(frozen=True, slots=True)
class Answered:
    value: Any


@dataclass(frozen=True, slots=True)
class Pending:
    """Nobody answered yet; keep the job and wait."""

    decision: Decision


@dataclass(frozen=True, slots=True)
class Refused:
    """Nobody can or will answer; the run cannot go on past this."""

    decision: Decision
    reason: str


type Resolution = Answered | Pending | Refused


class DecisionPolicy(Protocol):
    def resolve(self, decision: Decision, /) -> Resolution: ...


class _Declined:
    def __repr__(self) -> str:
        return "DECLINED"


DECLINED: Final = _Declined()
"""What an `ask` function returns when the person declined to answer."""


def _preset(answers: Mapping[str, Any], decision: Decision) -> Answered | None:
    if decision.id in answers:
        return Answered(answers[decision.id])
    return None


def _unanswered(decision: Decision) -> str:
    reason = f"Nobody could answer: {decision.prompt}"
    return f"{reason} ({decision.hint})" if decision.hint else reason


@dataclass(frozen=True, slots=True)
class InteractivePolicy:
    ask: Callable[[Decision], Any]
    """Puts the question to a person; returns the answer or `DECLINED`."""
    answers: Mapping[str, Any] = field(default_factory=dict)

    def resolve(self, decision: Decision, /) -> Resolution:
        preset = _preset(self.answers, decision)
        if preset is not None:
            return preset
        answer = self.ask(decision)
        if answer is DECLINED:
            return Refused(decision, "Declined")
        return Answered(answer)


@dataclass(frozen=True, slots=True)
class SafePolicy:
    answers: Mapping[str, Any] = field(default_factory=dict)

    def resolve(self, decision: Decision, /) -> Resolution:
        return _preset(self.answers, decision) or Pending(decision)


@dataclass(frozen=True, slots=True)
class UnattendedPolicy:
    answers: Mapping[str, Any] = field(default_factory=dict)

    def resolve(self, decision: Decision, /) -> Resolution:
        return _preset(self.answers, decision) or Refused(
            decision, _unanswered(decision)
        )


def policy_for(
    mode: AutomationMode,
    *,
    ask: Callable[[Decision], Any] | None = None,
    answers: Mapping[str, Any] | None = None,
) -> DecisionPolicy:
    """The policy a run in `mode` uses. Interactive needs someone to `ask`."""
    answers = dict(answers or {})
    if mode is AutomationMode.INTERACTIVE:
        if ask is None:
            raise ValueError("An interactive run needs a way to ask questions")
        return InteractivePolicy(ask, answers)
    if mode is AutomationMode.SAFE:
        return SafePolicy(answers)
    return UnattendedPolicy(answers)


class DecisionStop(Exception):
    """A decision stopped the run, pending or refused."""

    def __init__(self, resolution: Pending | Refused) -> None:
        self.resolution = resolution
        message = (
            resolution.reason
            if isinstance(resolution, Refused)
            else f"Waiting for input: {resolution.decision.prompt}"
        )
        super().__init__(message)

    @property
    def decision(self) -> Decision:
        return self.resolution.decision


def require(policy: DecisionPolicy, decision: Decision) -> Any:
    """The answer to `decision`, or `DecisionStop` if there is none."""
    resolution = policy.resolve(decision)
    if isinstance(resolution, Answered):
        return resolution.value
    raise DecisionStop(resolution)
