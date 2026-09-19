"""Coverage for the retry and timeout policy every image host now shares.

Each host used to hand-roll its own `for attempt in range(3)` loop with two
ways out of it -- a `continue` for a retryable status and an `except` for a
dropped connection -- so how many attempts an image actually got depended on
which way the host happened to fail. And none of them set a timeout at all.
"""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import aiohttp
import pytest

from src.backend.image_host_uploading.base_image_host import ImageUploadRequest
from src.backend.image_host_uploading.pixhost import PixhostUploader, pixhost_upload
from src.backend.image_host_uploading.retry import (
    RetryableStatus,
    image_client_timeout,
    retry_image_upload,
)
from src.packages.custom_types import ImageUploadData


class _MockResponse:
    def __init__(self, status: int, json_data: dict[str, Any] | None = None) -> None:
        self.status = status
        self.reason = "Service Unavailable" if status != 200 else "OK"
        self._json_data = json_data or {}

    async def json(self) -> dict[str, Any]:
        return self._json_data

    async def __aenter__(self) -> "_MockResponse":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


# --------------------------------------------------------------------------
# the timeout
# --------------------------------------------------------------------------
def test_the_timeout_bounds_silence_not_transfer() -> None:
    """A screenshot PNG can take longer than the configured 60 seconds.

    Capping the total would abort uploads that are progressing perfectly well,
    which is the opposite of what someone raising a timeout wants. What is
    worth bounding is a host that has stopped answering.
    """
    timeout = image_client_timeout(60)

    assert timeout is not None
    assert timeout.total is None
    assert timeout.sock_connect == 60
    assert timeout.sock_read == 60


@pytest.mark.parametrize("value", [None, 0, -1])
def test_no_timeout_leaves_the_library_default_alone(value: int | None) -> None:
    """`ClientSession(timeout=None)` already means "keep the default"."""
    assert image_client_timeout(value) is None


def test_a_hosts_session_is_given_the_requested_timeout(tmp_path: Path) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake image data")
    seen: list[aiohttp.ClientTimeout | None] = []

    def record(value: int | None) -> aiohttp.ClientTimeout | None:
        result = image_client_timeout(value)
        seen.append(result)
        return result

    post = MagicMock(
        return_value=_MockResponse(
            200, {"th_url": "https://t60.pixhost.to/thumbs/1/1.png"}
        )
    )
    with (
        patch("src.backend.image_host_uploading.pixhost.image_client_timeout", record),
        patch("aiohttp.ClientSession.post", post),
    ):
        asyncio.run(
            PixhostUploader().upload(ImageUploadRequest(filepaths=[image], timeout=90))
        )

    assert seen and seen[0] is not None
    assert seen[0].sock_read == 90


# --------------------------------------------------------------------------
# the attempt budget
# --------------------------------------------------------------------------
def test_a_retryable_status_and_a_dropped_connection_share_one_budget() -> None:
    """They used to be two paths through the same counter."""
    for error in (RetryableStatus(503), aiohttp.ClientError(), TimeoutError()):
        calls = 0

        async def always_fails(exc: BaseException = error) -> str:
            nonlocal calls
            calls += 1
            raise exc

        result = asyncio.run(
            retry_image_upload(always_fails, host_name="Test", attempts=3)
        )

        assert result is None, error
        assert calls == 3, error


def test_a_recovered_attempt_stops_the_retry() -> None:
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 2:
            raise RetryableStatus(429, "slow down")
        return "uploaded"

    assert asyncio.run(retry_image_upload(flaky, host_name="Test", attempts=3)) == (
        "uploaded"
    )
    assert calls == 2


def test_a_host_that_keeps_saying_503_gives_up_and_reports_no_url(
    tmp_path: Path,
) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake image data")
    post = MagicMock(return_value=_MockResponse(503))

    with patch("aiohttp.ClientSession.post", post):
        results = asyncio.run(pixhost_upload(filepaths=[image], attempts=2))

    assert results is not None
    assert results[0] == ImageUploadData(None, None)
    assert post.call_count == 2


def test_an_outright_refusal_is_not_retried(tmp_path: Path) -> None:
    """403 says the same thing however many times it is asked."""
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake image data")
    post = MagicMock(return_value=_MockResponse(403))

    with patch("aiohttp.ClientSession.post", post):
        results = asyncio.run(pixhost_upload(filepaths=[image], attempts=3))

    assert results is not None
    assert results[0] == ImageUploadData(None, None)
    assert post.call_count == 1
