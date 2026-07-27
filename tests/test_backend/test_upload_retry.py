from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import SignalInstance
from tenacity.wait import wait_none

import src.backend.process as process_module
from src.backend.process import ProcessBackEnd
from src.backend.upload_retry import (
    UploadFailurePhase,
    UploadRetryAction,
)
from src.config.config import ConfigManager
from src.enums.tracker_selection import TrackerSelection
from src.exceptions import ProcessCancelled, TrackerClientError, TrackerError


def _backend() -> ProcessBackEnd:
    backend = object.__new__(ProcessBackEnd)
    backend.config = cast(
        ConfigManager,
        SimpleNamespace(settings=SimpleNamespace(general=SimpleNamespace(timeout=60))),
    )
    return backend


def _kwargs(tmp_path: Path) -> dict[str, Any]:
    return {
        "tracker": TrackerSelection.AITHER,
        "torrent_path": tmp_path / "release.torrent",
        "tracker_health_cache": {},
        "queued_status_update": MagicMock(),
        "queued_text_update": MagicMock(),
        "caught_error": cast(SignalInstance, MagicMock()),
    }


def test_transient_upload_failure_is_retried_automatically(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(process_module, "ensure_tracker_health", lambda **_kwargs: None)
    monkeypatch.setattr(
        process_module, "wait_exponential", lambda **_kwargs: wait_none()
    )
    upload = MagicMock(
        side_effect=[TrackerError("temporary timeout", retryable=True), True]
    )
    kwargs = _kwargs(tmp_path)

    result, skipped = _backend()._upload_tracker_with_retry(
        upload_request=upload,
        upload_retry_cb=None,
        **kwargs,
    )

    assert result is True
    assert skipped is False
    assert upload.call_count == 2
    kwargs["queued_status_update"].assert_called_once()


def test_permanent_failure_can_be_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(process_module, "ensure_tracker_health", lambda **_kwargs: None)
    upload = MagicMock(side_effect=TrackerError("invalid API key", retryable=False))
    callback = MagicMock(return_value=UploadRetryAction.SKIP)
    kwargs = _kwargs(tmp_path)

    result, skipped = _backend()._upload_tracker_with_retry(
        upload_request=upload,
        upload_retry_cb=callback,
        **kwargs,
    )

    assert result is None
    assert skipped is True
    callback.assert_called_once()
    failure = callback.call_args.args[0]
    assert failure.phase is UploadFailurePhase.UPLOAD
    assert failure.attempt == 1
    assert upload.call_count == 1


def test_cancel_decision_stops_processing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(process_module, "ensure_tracker_health", lambda **_kwargs: None)
    upload = MagicMock(side_effect=TrackerError("tracker unavailable", retryable=False))
    kwargs = _kwargs(tmp_path)

    with pytest.raises(ProcessCancelled):
        _backend()._upload_tracker_with_retry(
            upload_request=upload,
            upload_retry_cb=lambda _failure: UploadRetryAction.CANCEL,
            **kwargs,
        )

    assert upload.call_count == 1


def test_user_retry_runs_the_upload_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A RETRY decision restarts the whole attempt budget and can succeed."""
    monkeypatch.setattr(process_module, "ensure_tracker_health", lambda **_kwargs: None)
    upload = MagicMock(
        side_effect=[TrackerError("invalid API key", retryable=False), True]
    )
    callback = MagicMock(return_value=UploadRetryAction.RETRY)
    kwargs = _kwargs(tmp_path)

    result, skipped = _backend()._upload_tracker_with_retry(
        upload_request=upload,
        upload_retry_cb=callback,
        **kwargs,
    )

    assert result is True
    assert skipped is False
    assert upload.call_count == 2
    callback.assert_called_once()


def test_automatic_attempts_are_exhausted_before_prompting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Retryable failures use the full automatic budget, then reach the user."""
    monkeypatch.setattr(process_module, "ensure_tracker_health", lambda **_kwargs: None)
    monkeypatch.setattr(
        process_module, "wait_exponential", lambda **_kwargs: wait_none()
    )
    upload = MagicMock(side_effect=TrackerError("temporary timeout", retryable=True))
    callback = MagicMock(return_value=UploadRetryAction.SKIP)
    kwargs = _kwargs(tmp_path)

    result, skipped = _backend()._upload_tracker_with_retry(
        upload_request=upload,
        upload_retry_cb=callback,
        **kwargs,
    )

    assert result is None
    assert skipped is True
    assert upload.call_count == ProcessBackEnd.AUTOMATIC_UPLOAD_ATTEMPTS
    failure = callback.call_args.args[0]
    assert failure.attempt == ProcessBackEnd.AUTOMATIC_UPLOAD_ATTEMPTS


def test_server_accepted_failure_prompts_on_the_first_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A possibly-accepted upload must reach the user without a silent re-POST."""
    monkeypatch.setattr(process_module, "ensure_tracker_health", lambda **_kwargs: None)
    upload = MagicMock(
        side_effect=TrackerError(
            "read timed out", retryable=True, server_accepted=True
        )
    )
    callback = MagicMock(return_value=UploadRetryAction.SKIP)
    kwargs = _kwargs(tmp_path)

    result, skipped = _backend()._upload_tracker_with_retry(
        upload_request=upload,
        upload_retry_cb=callback,
        **kwargs,
    )

    assert result is None
    assert skipped is True
    assert upload.call_count == 1
    failure = callback.call_args.args[0]
    assert failure.server_accepted is True


def test_injection_retry_prompts_and_succeeds(tmp_path: Path) -> None:
    """Injection failures are transient and carry no duplicate risk."""
    backend = _backend()
    inject = MagicMock(side_effect=[TrackerClientError("client offline"), None])
    backend._handle_injection = inject  # type: ignore[method-assign]
    callback = MagicMock(return_value=UploadRetryAction.RETRY)

    injected = backend._inject_with_user_retry(
        tracker=TrackerSelection.AITHER,
        tracker_name="Aither",
        torrent_path=tmp_path / "release.torrent",
        file_input=tmp_path / "release.mkv",
        queued_text_update=MagicMock(),
        queued_status_update=MagicMock(),
        caught_error=cast(SignalInstance, MagicMock()),
        upload_retry_cb=callback,
    )

    assert injected is True
    assert inject.call_count == 2
    failure = callback.call_args.args[0]
    assert failure.phase is UploadFailurePhase.INJECTION
    assert failure.server_accepted is False


def test_injection_failure_without_callback_is_reported_once(tmp_path: Path) -> None:
    backend = _backend()
    backend._handle_injection = MagicMock(  # type: ignore[method-assign]
        side_effect=TrackerClientError("client offline")
    )
    status_update = MagicMock()

    injected = backend._inject_with_user_retry(
        tracker=TrackerSelection.AITHER,
        tracker_name="Aither",
        torrent_path=tmp_path / "release.torrent",
        file_input=tmp_path / "release.mkv",
        queued_text_update=MagicMock(),
        queued_status_update=status_update,
        caught_error=cast(SignalInstance, MagicMock()),
        upload_retry_cb=None,
    )

    assert injected is False
