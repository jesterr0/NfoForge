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
from src.context.processing_context import ProcessingContext
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


def test_upload_failure_message_has_credentials_scrubbed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Deleting the ``scrub_secrets()`` call must be caught by a test, not
    just by review: drive the real failure path with a message containing a
    tracker API token and assert it never reaches the callback."""
    monkeypatch.setattr(process_module, "ensure_tracker_health", lambda **_kwargs: None)
    upload = MagicMock(
        side_effect=TrackerError(
            "Failed to upload: /api/torrents/upload?api_token=SECRETKEY123",
            retryable=False,
        )
    )
    callback = MagicMock(return_value=UploadRetryAction.SKIP)
    kwargs = _kwargs(tmp_path)

    _backend()._upload_tracker_with_retry(
        upload_request=upload,
        upload_retry_cb=callback,
        **kwargs,
    )

    callback.assert_called_once()
    failure = callback.call_args.args[0]
    assert "SECRETKEY123" not in failure.message
    assert "api_token=[redacted]" in failure.message


def test_download_phase_skip_is_reported_as_kept_not_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A DOWNLOAD-phase failure means the upload already succeeded; only
    fetching the tracker's copy of the torrent failed. Choosing SKIP there
    must not be reported the same way as a genuine skip, or a user reading
    the status afterwards could mistakenly re-upload by hand."""
    monkeypatch.setattr(process_module, "ensure_tracker_health", lambda **_kwargs: None)
    upload = MagicMock(
        side_effect=TrackerError(
            "Failed to download torrent from Aither: connection reset",
            retryable=True,
            server_accepted=True,
            phase="download",
        )
    )
    callback = MagicMock(return_value=UploadRetryAction.SKIP)
    status_update = MagicMock()
    text_update = MagicMock()
    kwargs = _kwargs(tmp_path)
    kwargs["queued_status_update"] = status_update
    kwargs["queued_text_update"] = text_update

    result, skipped = _backend()._upload_tracker_with_retry(
        upload_request=upload,
        upload_retry_cb=callback,
        **kwargs,
    )

    assert result is None
    assert skipped is True
    failure = callback.call_args.args[0]
    assert failure.phase is UploadFailurePhase.DOWNLOAD

    final_status_calls = [call.args for call in status_update.call_args_list]
    assert (str(TrackerSelection.AITHER), "⏭ Skipped") not in final_status_calls
    assert (
        str(TrackerSelection.AITHER),
        "⚠️ Uploaded - tracker torrent not downloaded",
    ) in final_status_calls

    final_text_calls = "".join(call.args[0] for call in text_update.call_args_list)
    assert "skipped upload" not in final_text_calls.lower()
    assert "upload succeeded" in final_text_calls.lower()


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
        side_effect=TrackerError("read timed out", retryable=True, server_accepted=True)
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


def test_injection_status_text_scrubs_credentials_without_callback(
    tmp_path: Path,
) -> None:
    """rTorrent embeds credentials as userinfo in its host URI, and
    RTorrentClient.inject_torrent has no exception handling of its own, so
    an xmlrpc.client.ProtocolError carrying the full netloc can reach this
    status line."""
    backend = _backend()
    backend._handle_injection = MagicMock(  # type: ignore[method-assign]
        side_effect=TrackerClientError(
            "<ProtocolError for https://user:hunter2@host.example/rpc: "
            "500 Internal Server Error>"
        )
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
    status_text = status_update.call_args.args[1]
    assert "hunter2" not in status_text


def test_injection_status_and_message_scrub_credentials_after_skip(
    tmp_path: Path,
) -> None:
    backend = _backend()
    backend._handle_injection = MagicMock(  # type: ignore[method-assign]
        side_effect=TrackerClientError(
            "<ProtocolError for https://user:hunter2@host.example/rpc: "
            "500 Internal Server Error>"
        )
    )
    callback = MagicMock(return_value=UploadRetryAction.SKIP)
    status_update = MagicMock()

    injected = backend._inject_with_user_retry(
        tracker=TrackerSelection.AITHER,
        tracker_name="Aither",
        torrent_path=tmp_path / "release.torrent",
        file_input=tmp_path / "release.mkv",
        queued_text_update=MagicMock(),
        queued_status_update=status_update,
        caught_error=cast(SignalInstance, MagicMock()),
        upload_retry_cb=callback,
    )

    assert injected is False
    failure = callback.call_args.args[0]
    assert "hunter2" not in failure.message
    final_status_text = status_update.call_args.args[1]
    assert "hunter2" not in final_status_text


def test_injection_cancel_marks_remaining_trackers_and_disconnects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A CANCEL decision at an injection prompt must run the same cleanup as
    a CANCEL decision at an upload prompt: mark the remaining trackers
    cancelled and disconnect the torrent clients.

    This exercises the real `process_trackers` loop (not
    `_inject_with_user_retry` in isolation) because the defect this guards
    against was in how the two call sites did, or did not, share the
    surrounding `try`/`except ProcessCancelled` handler: a `ProcessCancelled`
    raised from injection used to escape `process_trackers` entirely,
    skipping both the per-tracker cancellation status updates and
    `disconnect_from_clients()`.
    """
    monkeypatch.setattr(process_module, "ensure_tracker_health", lambda **_kwargs: None)
    monkeypatch.setattr(
        process_module, "generate_torrent", lambda **_kwargs: MagicMock()
    )
    monkeypatch.setattr(
        process_module,
        "write_torrent",
        lambda *_a, **_kwargs: tmp_path / "written.torrent",
    )
    monkeypatch.setattr(
        process_module,
        "build_series_release_info",
        lambda *_a, **_kwargs: MagicMock(),
    )

    tracker_info = SimpleNamespace(upload_enabled=True, nfo_template=None)
    backend = object.__new__(ProcessBackEnd)
    backend.config = cast(
        ConfigManager,
        SimpleNamespace(
            settings=SimpleNamespace(
                general=SimpleNamespace(
                    timeout=60,
                    enable_mkbrr=False,
                    enable_plugins=False,
                    enable_prompt_overview=False,
                ),
                trackers=SimpleNamespace(
                    by_selection=lambda: {
                        TrackerSelection.AITHER: tracker_info,
                        TrackerSelection.BEYOND_HD: tracker_info,
                    }
                ),
                user_tokens=SimpleNamespace(tokens={}),
                dependencies=SimpleNamespace(mkbrr=None),
            )
        ),
    )
    backend.template_selector_be = SimpleNamespace(
        load_templates=lambda: None, read_template=lambda name=None: None
    )
    backend.handle_images_for_trackers = MagicMock(return_value={})  # type: ignore[method-assign]
    backend.determine_max_piece_size = MagicMock(return_value=None)  # type: ignore[method-assign]
    backend.generate_tracker_title = MagicMock(return_value=None)  # type: ignore[method-assign]
    backend.upload = MagicMock(return_value=True)  # type: ignore[method-assign]
    backend._handle_injection = MagicMock(  # type: ignore[method-assign]
        side_effect=TrackerClientError("client offline")
    )
    backend.disconnect_from_clients = MagicMock()  # type: ignore[method-assign]

    context = cast(
        ProcessingContext,
        SimpleNamespace(
            media_input=SimpleNamespace(
                require_input_path=lambda: tmp_path / "media.mkv"
            )
        ),
    )
    process_dict = {
        "Aither": {"path": tmp_path / "aither.torrent"},
        "BeyondHD": {"path": tmp_path / "beyondhd.torrent"},
    }
    status_updates: list[tuple[str, str]] = []

    with pytest.raises(ProcessCancelled):
        backend.process_trackers(
            process_dict=process_dict,
            queued_status_update=lambda tracker, status: status_updates.append(
                (tracker, status)
            ),
            queued_text_update=MagicMock(),
            queued_text_update_replace_last_line=MagicMock(),
            progress_bar_cb=MagicMock(),
            caught_error=cast(SignalInstance, MagicMock()),
            context=context,
            upload_retry_cb=lambda _failure: UploadRetryAction.CANCEL,
        )

    backend.disconnect_from_clients.assert_called_once()
    assert ("Aither", "⏹ Cancelled") in status_updates
    assert ("BeyondHD", "⏹ Cancelled") in status_updates
