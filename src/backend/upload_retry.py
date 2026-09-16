from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

import niquests

from src.enums.tracker_selection import TrackerSelection
from src.packages.custom_types import ImageHostRef

RETRY_ATTEMPTS = 3
"""Default number of attempts for automatic retries of a tracker operation."""


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


class TrackerRunOutcome(Enum):
    """How one tracker ended up in a processing run.

    The per-tracker status shown in the GUI is display text that is never read
    back, so this exists to answer one question structurally: may this tracker
    be uploaded again? Only `NOT_ATTEMPTED`, `SKIPPED` and `UPLOAD_FAILED` may
    -- see `is_safe_to_reupload`.
    """

    NOT_ATTEMPTED = auto()
    """The run ended before this tracker was reached."""

    SKIPPED = auto()
    """User skipped it before any upload request was sent."""

    UPLOAD_FAILED = auto()
    """The upload provably did not reach the tracker."""

    MAY_HAVE_UPLOADED = auto()
    """The request may have landed; re-uploading risks a duplicate."""

    UPLOADED = auto()
    """Upload succeeded."""

    INJECTION_FAILED = auto()
    """Upload succeeded but the torrent client injection did not."""

    UPLOAD_DISABLED = auto()
    """Not uploaded by configuration, so there is nothing to defer."""

    def is_safe_to_reupload(self) -> bool:
        """Whether uploading this tracker again cannot create a duplicate.

        This is the guard that lets a partially completed run be saved as a
        job: only trackers this returns True for are carried into it.
        """
        return self in {
            TrackerRunOutcome.NOT_ATTEMPTED,
            TrackerRunOutcome.SKIPPED,
            TrackerRunOutcome.UPLOAD_FAILED,
        }


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


def classify_upload_post_error(error: BaseException) -> tuple[bool | None, bool]:
    """Return ``(retryable, server_accepted)`` for an error raised by an upload POST.

    An upload POST cannot be re-sent blindly: if the request body already
    reached the tracker, retrying creates a duplicate torrent. Classify by
    whether the failure provably happened before the body was transmitted.

    A ``retryable`` of ``None`` means "unknown"; callers treat that as not
    safe to retry automatically.
    """
    # ConnectTimeout subclasses ConnectionError, so it must be tested first.
    if isinstance(error, niquests.exceptions.ConnectTimeout):
        return True, False
    if isinstance(error, niquests.exceptions.ReadTimeout):
        # The body was fully sent and the tracker was still processing it.
        return True, True
    if isinstance(error, niquests.exceptions.InvalidJSONError):
        # A response arrived but was not JSON (proxy or CDN error page). The
        # tracker may still have recorded the upload. Covers JSONDecodeError.
        return True, True
    if isinstance(error, niquests.exceptions.ConnectionError):
        # niquests' HTTPAdapter wraps the *entire* conn.urlopen() call --
        # which spans sending the request body and reading the response
        # headers -- in a single `except (ProtocolError, OSError) as err:
        # raise ConnectionError(err, request=request)`. Refused, DNS
        # failure, and a reset mid-send all surface as this same bare
        # ConnectionError, but so does a tracker that accepted a large
        # multipart upload and then reset while processing it. That is
        # physically the same failure as ReadTimeout (marked
        # server_accepted=True above), so this is not provably pre-body.
        return None, True
    return None, True


IMAGE_UPLOAD_ATTEMPTS = 3
"""Default number of automatic attempts per image before the user is asked."""


class ImageRetryAction(Enum):
    """The action selected after images failed to reach an image host."""

    RETRY = auto()
    """Send the failed positions to the same host again."""

    SWITCH_HOST = auto()
    """Send every image to a different host instead."""

    CANCEL = auto()
    """Abandon the run."""


@dataclass(frozen=True, slots=True)
class ImageUploadFailure:
    """User-facing details for images that did not reach one image host.

    Keyed by host rather than by tracker: one host serves every tracker
    pointed at it, so a tracker field could only ever name one of them. The
    trackers waiting on it are carried alongside instead, because which
    uploads are blocked is what makes the choice -- not which host failed.

    `failed_positions` indexes the run's sorted screenshot list, which is the
    same index the uploaded URLs are keyed by, so a retry can send exactly
    those files back and merge the answers into place.
    """

    host: ImageHostRef
    trackers: tuple[TrackerSelection, ...]
    failed_positions: tuple[int, ...]
    total: int
    attempt: int
    automatic_attempts: int
    timeout: int
    message: str


@dataclass(frozen=True, slots=True)
class ImageRetryDecision:
    """What the user chose in response to an `ImageUploadFailure`.

    A decision rather than a bare action because both of the ways forward
    carry data: retrying is worth offering only if the timeout can be raised
    with it, and switching hosts needs to say which host.
    """

    action: ImageRetryAction
    host: ImageHostRef | None = None
    """The destination for `SWITCH_HOST`; ignored otherwise."""

    timeout: int | None = None
    """Timeout to use for this attempt, or None to keep the configured one."""
