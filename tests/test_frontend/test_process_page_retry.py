from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QMessageBox, QWidget

import src.frontend.wizards.process as page_module
from src.backend.upload_retry import (
    UploadFailure,
    UploadFailurePhase,
    UploadRetryAction,
)
from src.enums.tracker_selection import TrackerSelection
from src.frontend.global_signals import GSigs
from src.frontend.wizards.process import ProcessPage


class _FakeButton:
    def __init__(self, label: str, role: object) -> None:
        self.label = label
        self.role = role


class _FakeMessageBox:
    """Stands in for QMessageBox so the slot's decisions are observable."""

    Icon = QMessageBox.Icon
    ButtonRole = QMessageBox.ButtonRole
    last: "_FakeMessageBox | None" = None
    click_label: str | None = None

    def __init__(self, parent: object = None) -> None:
        self.buttons: list[_FakeButton] = []
        self.default_button: _FakeButton | None = None
        self.informative_text = ""
        _FakeMessageBox.last = self

    def setIcon(self, *_a: object) -> None: ...
    def setWindowTitle(self, *_a: object) -> None: ...
    def setText(self, *_a: object) -> None: ...

    def setInformativeText(self, text: str) -> None:
        self.informative_text = text

    def addButton(self, label: str, role: object) -> _FakeButton:
        button = _FakeButton(label, role)
        self.buttons.append(button)
        return button

    def setDefaultButton(self, button: _FakeButton) -> None:
        self.default_button = button

    def exec(self) -> None: ...

    def clickedButton(self) -> _FakeButton | None:
        for button in self.buttons:
            if button.label == _FakeMessageBox.click_label:
                return button
        return None


def _failure(**overrides: object) -> UploadFailure:
    kwargs: dict = {
        "tracker": TrackerSelection.AITHER,
        "phase": UploadFailurePhase.UPLOAD,
        "message": "read timed out",
        "attempt": 1,
        "automatic_attempts": 3,
        "retryable": True,
        "server_accepted": False,
        "torrent_path": Path("release.torrent"),
    }
    kwargs.update(overrides)
    return UploadFailure(**kwargs)


@pytest.fixture(autouse=True)
def _reset_fake_message_box() -> None:
    _FakeMessageBox.click_label = None
    _FakeMessageBox.last = None


@pytest.fixture
def responses():
    """Record UploadRetryAction values emitted on the global response signal."""
    seen: list[UploadRetryAction] = []
    GSigs().upload_retry_response.connect(seen.append)
    yield seen
    GSigs().upload_retry_response.disconnect(seen.append)


def test_retry_prompt_returns_the_clicked_action(responses) -> None:
    _FakeMessageBox.click_label = "Skip tracker"
    with patch.object(page_module, "QMessageBox", _FakeMessageBox):
        ProcessPage._on_upload_retry_signal(QWidget(), _failure())

    assert responses == [UploadRetryAction.SKIP]


def test_worker_released_when_dialog_raises(responses) -> None:
    """A dialog failure must not leave the worker blocked in loop.exec_()."""
    boom = MagicMock(side_effect=RuntimeError("Internal C++ object already deleted"))
    boom.Icon = QMessageBox.Icon
    boom.ButtonRole = QMessageBox.ButtonRole

    with patch.object(page_module, "QMessageBox", boom):
        ProcessPage._on_upload_retry_signal(QWidget(), _failure())

    assert responses == [UploadRetryAction.CANCEL]


def test_default_button_is_not_retry_when_server_accepted(responses) -> None:
    """The dialog must not steer a reflexive Enter press into a duplicate."""
    _FakeMessageBox.click_label = "Skip tracker"
    with patch.object(page_module, "QMessageBox", _FakeMessageBox):
        ProcessPage._on_upload_retry_signal(QWidget(), _failure(server_accepted=True))

    default = _FakeMessageBox.last.default_button
    assert default is not None
    assert "Retry" not in default.label


def test_download_phase_offers_no_reupload(responses) -> None:
    """The upload already succeeded, so re-POSTing is a guaranteed duplicate."""
    _FakeMessageBox.click_label = "Keep upload, use local torrent"
    with patch.object(page_module, "QMessageBox", _FakeMessageBox):
        ProcessPage._on_upload_retry_signal(
            QWidget(), _failure(phase=UploadFailurePhase.DOWNLOAD, server_accepted=True)
        )

    labels = [button.label for button in _FakeMessageBox.last.buttons]
    assert not any("upload" in label.lower() and "keep" not in label.lower()
                   for label in labels), labels
    assert "Retry" not in labels
    assert responses == [UploadRetryAction.SKIP]
    assert "upload succeeded" in _FakeMessageBox.last.informative_text.lower()


def test_retry_is_relabelled_when_the_tracker_may_have_the_torrent(responses) -> None:
    _FakeMessageBox.click_label = "Re-upload (may duplicate)"
    with patch.object(page_module, "QMessageBox", _FakeMessageBox):
        ProcessPage._on_upload_retry_signal(QWidget(), _failure(server_accepted=True))

    assert responses == [UploadRetryAction.RETRY]
