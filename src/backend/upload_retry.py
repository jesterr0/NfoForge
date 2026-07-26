from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from src.enums.tracker_selection import TrackerSelection


class UploadRetryAction(Enum):
    """The action selected after an upload attempt needs user attention."""

    RETRY = auto()
    SKIP = auto()
    CANCEL = auto()


class UploadFailurePhase(Enum):
    """The phase in which a tracker job failed."""

    HEALTH_CHECK = auto()
    UPLOAD = auto()
    DOWNLOAD = auto()
    INJECTION = auto()


@dataclass(frozen=True, slots=True)
class UploadFailure:
    """User-facing details for a failed tracker operation."""

    tracker: TrackerSelection
    phase: UploadFailurePhase
    message: str
    attempt: int
    automatic_attempts: int
    retryable: bool
    server_accepted: bool = False
    torrent_path: Path | None = None
