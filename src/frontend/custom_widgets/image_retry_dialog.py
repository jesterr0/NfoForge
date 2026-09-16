from collections.abc import Sequence

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.backend.upload_retry import (
    ImageRetryAction,
    ImageRetryDecision,
    ImageUploadFailure,
)
from src.packages.custom_types import ImageHostRef

MIN_TIMEOUT_SECONDS = 2
MAX_TIMEOUT_SECONDS = 600
"""Wider than Settings -> General, which caps at 120.

This is the box someone reaches for precisely because the configured timeout
was not enough, so capping it at the configured maximum would answer the
problem with the thing that caused it. It applies to this attempt only.
"""


class ImageRetryDialog(QDialog):
    """Offers a way past images that did not reach their host.

    A `QMessageBox` cannot carry the two things that make the choice useful --
    a bigger timeout and a different host -- so this is a plain dialog whose
    buttons read `results` once it closes.
    """

    def __init__(
        self,
        failure: ImageUploadFailure,
        hosts: Sequence[ImageHostRef],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("imageRetryDialog")
        self.setWindowTitle(f"Image upload failed: {failure.host}")

        # Cancel is what an unanswered prompt means everywhere else in the run,
        # so it is also what closing this window with the titlebar means.
        self.results = ImageRetryDecision(action=ImageRetryAction.CANCEL)
        self._failure = failure

        positions = ", ".join(str(index) for index in failure.failed_positions)
        waiting = ", ".join(str(tracker) for tracker in failure.trackers)
        summary = (
            f'<h3 style="margin: 0; margin-bottom: 6px;">{self.windowTitle()}</h3>'
            f"<span>{len(failure.failed_positions)} of {failure.total} image(s) "
            f"failed to upload after {failure.automatic_attempts} automatic "
            f"attempt(s).</span>"
            f'<br /><span style="color: #888;">Position(s): {positions}</span>'
        )
        if waiting:
            summary += f'<br /><span style="color: #888;">Waiting on: {waiting}</span>'
        info_lbl = QLabel(summary, wordWrap=True, parent=self)

        self.timeout_spin = QSpinBox(self)
        self.timeout_spin.setRange(MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS)
        self.timeout_spin.setValue(
            max(MIN_TIMEOUT_SECONDS, min(failure.timeout, MAX_TIMEOUT_SECONDS))
        )
        self.timeout_spin.setSuffix(" seconds")
        self.timeout_spin.setToolTip(
            "Connect and read budget for this attempt only. Raise it for a host "
            "that is slow rather than down."
        )

        self.host_combo = QComboBox(self)
        # The failing host is not offered as somewhere else to send them.
        self._hosts = [host for host in hosts if host != failure.host]
        for host in self._hosts:
            self.host_combo.addItem(str(host), host)
        self.host_combo.setToolTip(
            "Every image is sent to the new host, including the ones that "
            "already uploaded -- a tracker cannot take half its images from "
            "each."
        )

        form = QFormLayout()
        form.addRow("Timeout for this attempt:", self.timeout_spin)
        form.addRow("Or send them to:", self.host_combo)

        button_box = QDialogButtonBox(self)
        self.retry_btn = button_box.addButton(
            f"Retry {len(failure.failed_positions)} failed",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.switch_btn = button_box.addButton(
            "Switch host", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.cancel_btn = button_box.addButton(
            "Cancel run", QDialogButtonBox.ButtonRole.RejectRole
        )

        # Nothing to switch to is the common case for a single-host setup, and
        # a dead control says so more plainly than an empty list does.
        has_alternatives = bool(self._hosts)
        self.switch_btn.setEnabled(has_alternatives)
        self.host_combo.setEnabled(has_alternatives)
        if not has_alternatives:
            self.host_combo.addItem("No other image host is configured")

        self.retry_btn.clicked.connect(self._on_retry)
        self.switch_btn.clicked.connect(self._on_switch)
        self.cancel_btn.clicked.connect(self.reject)
        if isinstance(self.retry_btn, QPushButton):
            self.retry_btn.setDefault(True)

        layout = QVBoxLayout(self)
        layout.addWidget(info_lbl)
        layout.addLayout(form)
        layout.addWidget(button_box)

    def _chosen_timeout(self) -> int | None:
        """The spinbox value, or None when it was left where it started."""
        value = int(self.timeout_spin.value())
        return None if value == self._failure.timeout else value

    def _on_retry(self) -> None:
        self.results = ImageRetryDecision(
            action=ImageRetryAction.RETRY, timeout=self._chosen_timeout()
        )
        self.accept()

    def _on_switch(self) -> None:
        host = self.host_combo.currentData()
        if not isinstance(host, ImageHostRef):
            return
        self.results = ImageRetryDecision(
            action=ImageRetryAction.SWITCH_HOST,
            host=host,
            timeout=self._chosen_timeout(),
        )
        self.accept()
