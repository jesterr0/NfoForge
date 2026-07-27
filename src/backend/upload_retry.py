import re
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

import niquests

from src.enums.tracker_selection import TrackerSelection

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


_SECRET_QUERY_PARAM = re.compile(
    r"(?i)\b(api_token|api_key|apikey|passkey|rsskey|torrent_pass)=[^&\s\"']+"
)

# Matches the userinfo portion of a URI, e.g. the credentials rTorrent embeds
# in its host URI (`https://user:password@host/...`). An `xmlrpc.client.
# ProtocolError` copies that full netloc into its message, so this shape can
# reach on-screen status text the same way a query-string secret can.
_URI_USERINFO_PASSWORD = re.compile(r"(?i)(://[^/\s:@]+:)[^@\s]+(@)")


def scrub_secrets(text: str) -> str:
    """Redact credentials that transport errors copy out of a request URL."""
    text = _SECRET_QUERY_PARAM.sub(r"\1=[redacted]", text)
    text = _URI_USERINFO_PASSWORD.sub(r"\1[redacted]\2", text)
    return text
