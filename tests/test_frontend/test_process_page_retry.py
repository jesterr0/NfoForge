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
