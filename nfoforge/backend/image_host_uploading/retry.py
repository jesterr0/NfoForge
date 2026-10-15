import asyncio
from collections.abc import Awaitable, Callable

import aiohttp
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt
from tenacity.wait import wait_exponential

from nfoforge.backend.upload_retry import IMAGE_UPLOAD_ATTEMPTS
from nfoforge.logger.nfo_forge_logger import LOG

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
"""Statuses that say "later", not "no": rate limiting and server-side faults."""


class RetryableStatus(Exception):
    """A host answered, but with a status worth trying again.

    Raised rather than returned so that a retryable status and a dropped
    connection share one attempt budget and one backoff. Each host used to
    run those as two paths through the same counter -- a `continue` for the
    status and an `except` for the error -- which made the real number of
    attempts depend on which way a host happened to fail.
    """

    __slots__ = ("status", "reason")

    def __init__(self, status: int, reason: str | None = None) -> None:
        super().__init__(f"HTTP {status}{f' ({reason})' if reason else ''}")
        self.status = status
        self.reason = reason


RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    aiohttp.ClientError,
    asyncio.TimeoutError,
    RetryableStatus,
)


def image_client_timeout(timeout: int | None) -> aiohttp.ClientTimeout | None:
    """A connect/read budget for one image request, or None for aiohttp's default.

    Deliberately not a `total`. `general.timeout` is 60 seconds by default and
    a screenshot PNG can legitimately take longer than that to transfer, so a
    total cap would abort uploads that are progressing perfectly well. What is
    worth bounding is a host that has stopped answering, which is exactly what
    `sock_connect` and `sock_read` measure.

    None is returned rather than a permissive `ClientTimeout` because
    `ClientSession(timeout=None)` already means "keep the default", so an
    unset timeout leaves today's behaviour untouched.
    """
    if not timeout or timeout <= 0:
        return None
    return aiohttp.ClientTimeout(total=None, sock_connect=timeout, sock_read=timeout)


async def retry_image_upload[T](
    operation: Callable[[], Awaitable[T]],
    *,
    host_name: str,
    attempts: int = IMAGE_UPLOAD_ATTEMPTS,
) -> T | None:
    """Run one image operation with a bounded automatic retry budget.

    The async twin of `trackers.health._probe_tracker`, carrying the same
    backoff as `_upload_tracker_with_retry`: a host that is briefly unwell
    should cost a few seconds, not the run.

    Returns None once every attempt has failed. A per-image failure is a value
    here rather than an exception, because at this depth nothing knows which
    tracker was waiting on the image -- `assert_all_images_uploaded` is what
    turns a gap into an error, and the user prompt is what offers a way out.
    """
    retrying: AsyncRetrying = AsyncRetrying(
        retry=retry_if_exception_type(RETRYABLE_ERRORS),
        stop=stop_after_attempt(max(1, attempts)),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    try:
        return await retrying(operation)
    except RETRYABLE_ERRORS as error:
        LOG.warning(
            LOG.LOG_SOURCE.BE,
            f"{host_name}: upload failed after {attempts} attempts: {error}",
        )
    return None
