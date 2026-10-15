"""What a run reports as it goes.

A run never touches a progress bar or a log view. It emits events to an
`EventSink`, and each interface decides what to do with them: the desktop app
updates its widgets, the command line prints, a server would stream them. Every
event is a small frozen record that serializes to JSON with a `kind` field.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Protocol

from nfoforge.enums.automation import JobState
from nfoforge.logger.nfo_forge_logger import LOG


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Event:
    kind: ClassVar[str] = "event"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, **asdict(self)}


@dataclass(frozen=True, slots=True)
class StageStarted(Event):
    kind: ClassVar[str] = "stage_started"
    stage: str


@dataclass(frozen=True, slots=True)
class StageFinished(Event):
    kind: ClassVar[str] = "stage_finished"
    stage: str


@dataclass(frozen=True, slots=True)
class ProgressEvent(Event):
    """How far through a stage the run is.

    `current`/`total` are counts ("screenshot 3 of 6"); `percent` is for work
    that only knows a fraction. Either may be absent.
    """

    kind: ClassVar[str] = "progress"
    stage: str
    message: str
    current: int | None = None
    total: int | None = None
    percent: float | None = None


@dataclass(frozen=True, slots=True)
class LogLine(Event):
    kind: ClassVar[str] = "log"
    message: str
    level: LogLevel = LogLevel.INFO


@dataclass(frozen=True, slots=True)
class JobStateChanged(Event):
    kind: ClassVar[str] = "job_state"
    state: JobState
    detail: str = ""


@dataclass(frozen=True, slots=True)
class DecisionNeeded(Event):
    """A run stopped, or is waiting, on a question."""

    kind: ClassVar[str] = "decision_needed"
    decision: dict[str, Any] = field(default_factory=dict)


class EventSink(Protocol):
    def emit(self, event: Event, /) -> None: ...


class CollectingSink:
    """Keeps every event, in order. For tests and for replaying a run."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event, /) -> None:
        self.events.append(event)

    def of(self, kind: type[Event]) -> list[Any]:
        return [event for event in self.events if isinstance(event, kind)]


class CallbackSink:
    """Hands every event to a function."""

    def __init__(self, callback: Callable[[Event], None]) -> None:
        self._callback = callback

    def emit(self, event: Event, /) -> None:
        self._callback(event)


class LoggingSink:
    """Writes log lines and state changes to NfoForge's log; drops the rest."""

    _LEVELS: ClassVar[dict[LogLevel, str]] = {
        LogLevel.DEBUG: "debug",
        LogLevel.INFO: "info",
        LogLevel.WARNING: "warning",
        LogLevel.ERROR: "error",
    }

    def emit(self, event: Event, /) -> None:
        if isinstance(event, LogLine):
            getattr(LOG, self._LEVELS[event.level])(LOG.LOG_SOURCE.BE, event.message)
        elif isinstance(event, JobStateChanged):
            detail = f": {event.detail}" if event.detail else ""
            LOG.info(LOG.LOG_SOURCE.BE, f"Job {event.state}{detail}")


class FanOutSink:
    """Sends every event to several sinks."""

    def __init__(self, *sinks: EventSink) -> None:
        self._sinks = sinks

    def emit(self, event: Event, /) -> None:
        for sink in self._sinks:
            sink.emit(event)
