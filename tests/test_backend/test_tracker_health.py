from unittest.mock import ANY, MagicMock, patch

import niquests
import pytest
from tenacity.wait import wait_none

import src.backend.trackers.health as health_module
from src.backend.trackers.health import (
    HEALTH_CHECK_TIMEOUT_SECONDS,
    ensure_tracker_health,
)
from src.enums.tracker_selection import TRACKER_ROOT_URLS, TrackerSelection
from src.exceptions import TrackerError


@patch("niquests.Session.get")
def test_health_check_accepts_reachable_tracker_and_caches_result(
    get: MagicMock,
) -> None:
    response = MagicMock(status_code=200, reason="OK")
    get.return_value.__enter__.return_value = response
    cache: dict[TrackerSelection, bool] = {}

    ensure_tracker_health(TrackerSelection.AITHER, timeout=60, cache=cache)
    ensure_tracker_health(TrackerSelection.AITHER, timeout=60, cache=cache)

    assert cache == {TrackerSelection.AITHER: True}
    get.assert_called_once_with(
        TrackerSelection.AITHER.get_root_url(),
        headers=ANY,
        timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
        stream=True,
    )
    get.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("status_code", [500, 503])
@patch("niquests.Session.get")
def test_health_check_blocks_http_failures_and_caches_failure(
    get: MagicMock, status_code: int
) -> None:
    response = MagicMock(status_code=status_code, reason="Unavailable")
    get.return_value.__enter__.return_value = response
    cache: dict[TrackerSelection, bool] = {}

    with pytest.raises(TrackerError, match=f"HTTP {status_code}"):
        ensure_tracker_health(TrackerSelection.TORRENT_LEECH, timeout=60, cache=cache)
    with pytest.raises(TrackerError, match="is unavailable"):
        ensure_tracker_health(TrackerSelection.TORRENT_LEECH, timeout=60, cache=cache)

    assert cache == {TrackerSelection.TORRENT_LEECH: False}
    get.assert_called_once()


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 405, 429])
@patch("niquests.Session.get")
def test_health_check_accepts_reachable_client_responses(
    get: MagicMock, status_code: int
) -> None:
    response = MagicMock(status_code=status_code, reason="Client response")
    get.return_value.__enter__.return_value = response
    cache: dict[TrackerSelection, bool] = {}

    ensure_tracker_health(TrackerSelection.TORRENT_LEECH, timeout=60, cache=cache)

    assert cache == {TrackerSelection.TORRENT_LEECH: True}


@patch("niquests.Session.get")
def test_health_check_blocks_request_failures(
    get: MagicMock,
) -> None:
    get.side_effect = niquests.exceptions.RequestException("connection refused")
    cache: dict[TrackerSelection, bool] = {}

    with pytest.raises(TrackerError, match="connection refused"):
        ensure_tracker_health(TrackerSelection.PASS_THE_POPCORN, timeout=2, cache=cache)

    assert cache == {TrackerSelection.PASS_THE_POPCORN: False}
    assert get.call_count == 3
    get.assert_called_with(
        TrackerSelection.PASS_THE_POPCORN.get_root_url(),
        headers=ANY,
        timeout=2,
        stream=True,
    )


def test_health_check_has_a_root_url_for_every_tracker() -> None:
    assert set(TRACKER_ROOT_URLS) == set(TrackerSelection)


def test_attempts_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The caller owns the retry budget so nested loops cannot multiply it."""
    calls = 0

    def _fail(url: str, timeout: int) -> tuple[int, str | None]:
        nonlocal calls
        calls += 1
        raise niquests.RequestException("unreachable")

    monkeypatch.setattr(health_module, "_probe_tracker_once", _fail)
    cache: dict[TrackerSelection, bool] = {}

    with pytest.raises(TrackerError):
        ensure_tracker_health(TrackerSelection.AITHER, 5, cache, attempts=1)

    assert calls == 1
    assert cache[TrackerSelection.AITHER] is False


def test_default_attempts_still_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def _fail(url: str, timeout: int) -> tuple[int, str | None]:
        nonlocal calls
        calls += 1
        raise niquests.RequestException("unreachable")

    # Matches the existing pattern in tests/test_backend/test_upload_retry.py:46
    # so the retry runs without real backoff sleeps.
    monkeypatch.setattr(health_module, "_probe_tracker_once", _fail)
    monkeypatch.setattr(
        health_module, "wait_exponential", lambda **_kwargs: wait_none()
    )

    with pytest.raises(TrackerError):
        ensure_tracker_health(TrackerSelection.AITHER, 5, {})

    assert calls == 3
