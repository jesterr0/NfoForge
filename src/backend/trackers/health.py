from collections.abc import MutableMapping

import niquests
from niquests import RequestException
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.backend.trackers.utils import TRACKER_HEADERS
from src.backend.upload_retry import RETRY_ATTEMPTS
from src.enums.tracker_selection import TrackerSelection
from src.exceptions import TrackerError

HEALTH_CHECK_TIMEOUT_SECONDS = 5


def _probe_tracker_once(url: str, timeout: int) -> tuple[int, str | None]:
    with niquests.get(
        url,
        headers=TRACKER_HEADERS,
        timeout=timeout,
        stream=True,
    ) as response:
        if response.status_code is None:
            raise RequestException("No HTTP status code received")
        return response.status_code, response.reason


def _probe_tracker(url: str, timeout: int, attempts: int) -> tuple[int, str | None]:
    """Probe the tracker root, retrying up to ``attempts`` times."""
    return Retrying(
        retry=retry_if_exception_type(RequestException),
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
        reraise=True,
    )(_probe_tracker_once, url, timeout)


def ensure_tracker_health(
    tracker: TrackerSelection,
    timeout: int,
    cache: MutableMapping[TrackerSelection, bool],
    *,
    attempts: int = RETRY_ATTEMPTS,
) -> None:
    """Verify a tracker root is reachable once per processing run."""
    cached = cache.get(tracker)
    if cached is not None:
        if not cached:
            raise TrackerError(
                f"{tracker} is unavailable",
                retryable=True,
                phase="health_check",
            )
        return

    probe_timeout = max(1, min(timeout, HEALTH_CHECK_TIMEOUT_SECONDS))

    try:
        status_code, reason = _probe_tracker(
            tracker.get_root_url(),
            probe_timeout,
            attempts,
        )
    except RequestException as error:
        cache[tracker] = False
        raise TrackerError(
            f"{tracker} is unavailable: {error}",
            retryable=True,
            phase="health_check",
        ) from error

    if status_code >= 400:
        cache[tracker] = False
        detail = f" ({reason})" if reason else ""
        raise TrackerError(
            f"{tracker} is unavailable (HTTP {status_code}{detail})",
            retryable=status_code == 429 or status_code >= 500,
            phase="health_check",
            status_code=status_code,
        )

    cache[tracker] = True
