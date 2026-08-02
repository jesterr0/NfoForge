from pathlib import Path
from typing import cast

from pymediainfo import MediaInfo
from PySide6.QtWidgets import QMessageBox
import pytest

from src.context.processing_context import ProcessingContext
from src.frontend.wizards.media_input import MediaInput


def test_media_info_failure_reports_missing_files_and_restores_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = MediaInput(config=None, context=ProcessingContext(), parent=None)  # type: ignore[arg-type]
    expected = (Path("one.mkv"), Path("two.mkv"))
    page._files_being_processed = expected
    page._loading_completed = True
    page._progress_connected = False
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, _title, message: messages.append(message),
    )

    page._worker_finished(
        (
            {expected[0]: cast(MediaInfo, object())},
            {expected[1]: "OSError: unreadable stream"},
        ),
    )

    assert page._loading_completed is False
    assert page._files_being_processed == ()
    assert len(messages) == 1
    assert "two.mkv" in messages[0]
    assert "unreadable stream" in messages[0]
    assert "one.mkv" not in messages[0]


def test_media_info_empty_result_does_not_raise_or_leave_ui_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = MediaInput(config=None, context=ProcessingContext(), parent=None)  # type: ignore[arg-type]
    page._files_being_processed = (Path("missing.mkv"),)
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, _title, message: messages.append(message),
    )

    page._worker_finished(({}, {}))

    assert page._loading_completed is False
    assert messages == ["Failed to detect MediaInfo for the selected files."]
