"""Runs a set of prepared jobs and shows what is happening while it does.

The queue deliberately does not borrow the wizard's process page. That page is
built around one interactive run: it owns a tracker tree keyed to a single
release, a per-run outcome map used to offer a deferred save, and a button
state machine that assumes somebody is answering prompts. A queue has none of
those and several jobs' worth of the ones it does have, so it gets its own
window -- which is also the only place a Cancel button can sensibly live.
"""

from collections.abc import Sequence
from html import escape
from pathlib import Path
import traceback

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.backend.job_queue import (
    JobDisposition,
    JobQueueRunner,
    QueuedJobOutcome,
    QueuedJobResult,
)
from src.backend.process import ProcessBackEnd
from src.config.config import ConfigManager
from src.logger.nfo_forge_logger import LOG
from src.utils.secret_redaction import scrub_secrets

_RESULT_LABELS = {
    QueuedJobResult.UPLOADED: "✅ Uploaded",
    QueuedJobResult.SKIPPED_DUPES: "⏭ Possible duplicate",
    QueuedJobResult.SKIPPED_UNVERIFIED: "⏭ Could not verify",
    QueuedJobResult.SKIPPED_UNUSABLE: "⏭ Unusable",
    QueuedJobResult.SKIPPED_NOT_PREPARED: "⏭ Not prepared",
    QueuedJobResult.FAILED: "❌ Failed",
}

_DISPOSITION_LABELS = {
    JobDisposition.KEPT: "kept",
    JobDisposition.NARROWED: "kept for the trackers that did not upload",
    JobDisposition.DELETED: "removed",
}


class _QueueThread(QThread):
    """Drives `JobQueueRunner` off the GUI thread.

    Nothing here waits on a dialog: a queue only accepts prepared jobs, and the
    runner passes no prompt or retry callbacks, so it runs to completion on its
    own. Its own thread type rather than the process page's `BaseWorker`, so the
    queue does not import from the page it was extracted out of.
    """

    text = Signal(str)
    text_replace = Signal(str)
    tracker_status = Signal(str, str)
    progress = Signal(float)
    job_started = Signal(int, str)
    job_finished = Signal(int, object)
    results = Signal(object)
    failed = Signal(str, str)

    def __init__(
        self,
        backend: ProcessBackEnd,
        config: ConfigManager,
        job_paths: list[Path],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.config = config
        self.job_paths = job_paths
        self._cancelled = False

    def cancel(self) -> None:
        """Stop before the next job. The one in flight is left to finish.

        Tearing down mid-upload is what risks a half-sent release, so the only
        safe cancel point is between jobs.
        """
        self._cancelled = True

    def run(self) -> None:
        try:
            runner = JobQueueRunner(
                backend=self.backend,
                config=self.config,
                text_update=self.text.emit,
                text_replace_last_update=self.text_replace.emit,
                status_update=self.tracker_status.emit,
                progress_cb=self.progress.emit,
                is_cancelled=lambda: self._cancelled,
                job_started=self.job_started.emit,
                job_finished=self.job_finished.emit,
            )
            self.results.emit(runner.run(self.job_paths))
        except Exception as error:
            self.failed.emit(scrub_secrets(str(error)), traceback.format_exc())


class JobQueueDialog(QDialog):
    """Shows a queue of prepared jobs running, one after another."""

    def __init__(
        self,
        job_paths: Sequence[Path],
        config: ConfigManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("jobQueueDialog")
        self.setWindowTitle("Job Queue")
        self.setSizeGripEnabled(True)
        self.resize(900, 620)

        self.job_paths = list(job_paths)
        self.config = config
        self._thread: _QueueThread | None = None
        self._current_index = 0
        """Which job's tracker rows incoming status belongs to.

        The runner is strictly sequential and always announces a job before any
        of its trackers report, so tracking the current job here is enough to
        key status on (job, tracker) without widening the callback.
        """
        self._tracker_rows: dict[tuple[int, str], QTreeWidgetItem] = {}

        self.header_lbl = QLabel(
            f"<h3 style='margin: 0;'>Running {len(self.job_paths)} job(s)</h3>"
            "<i><span>Each job is duplicate checked immediately before it "
            "uploads. A job that finds a duplicate, or that cannot be checked, "
            "is skipped and kept for you to review.</span></i>",
            wordWrap=True,
            parent=self,
        )

        self.job_tree = QTreeWidget(self)
        self.job_tree.setFrameShape(QFrame.Shape.Box)
        self.job_tree.setFrameShadow(QFrame.Shadow.Sunken)
        # jobs at the top, their trackers as children -- the one structure that
        # can hold the same tracker appearing in more than one job
        self.job_tree.setRootIsDecorated(True)
        self.job_tree.setColumnCount(4)
        self.job_tree.setHeaderLabels(("#", "Job / tracker", "Status", "Detail"))
        self.job_tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = self.job_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for index, path in enumerate(self.job_paths, start=1):
            self.job_tree.addTopLevelItem(
                QTreeWidgetItem((str(index), path.name, "Queued", ""))
            )

        self.text_widget = QTextEdit(self)
        self.text_widget.setReadOnly(True)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setToolTip(
            "Stop before the next job starts. The job currently uploading is "
            "left to finish, since interrupting an upload is what risks a "
            "half-sent release"
        )
        self.cancel_btn.clicked.connect(self._on_cancel)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close, parent=self
        )
        self.button_box.rejected.connect(self.reject)
        close_button = self.button_box.button(QDialogButtonBox.StandardButton.Close)
        if close_button:
            close_button.setEnabled(False)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)
        bottom_row.addWidget(self.cancel_btn)
        bottom_row.addWidget(self.button_box)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.header_lbl)
        main_layout.addWidget(self.job_tree, stretch=2)
        main_layout.addWidget(self.text_widget, stretch=3)
        main_layout.addWidget(self.progress_bar)
        main_layout.addLayout(bottom_row)

    # ------------------------------------------------------------------
    def start(self) -> None:
        """Begin the queue. Separate from construction on purpose.

        A thread started inside `__init__` is a thread the caller never chose
        to start and cannot avoid: the object exists and is already running
        before it is even assigned to a variable. Splitting this out gives the
        caller (and a test) a dialog it can inspect or discard before any
        thread exists, and means a dropped dialog is never one that still has
        a job in flight.
        """
        self._start()

    def _start(self) -> None:
        self._thread = _QueueThread(
            backend=ProcessBackEnd(self.config),
            config=self.config,
            job_paths=self.job_paths,
            parent=self,
        )
        self._thread.text.connect(self._on_text)
        self._thread.text_replace.connect(self._on_text_replace)
        self._thread.tracker_status.connect(self._on_tracker_status)
        self._thread.progress.connect(self._on_progress)
        self._thread.job_started.connect(self._on_job_started)
        self._thread.job_finished.connect(self._on_job_finished)
        self._thread.results.connect(self._on_results)
        self._thread.failed.connect(self._on_failed)
        self._thread.finished.connect(self._on_queue_finished)
        self._thread.start()

    def _item(self, index: int) -> QTreeWidgetItem | None:
        return self.job_tree.topLevelItem(index - 1)

    # ------------------------------------------------------------------
    @Slot(str)
    def _on_text(self, message: str) -> None:
        # scrubbed on the way in, as the process page does: queue log lines
        # carry tracker responses, which can carry credentials
        safe_message = scrub_secrets(message)
        cursor = self.text_widget.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(safe_message)
        self.text_widget.setTextCursor(cursor)
        self.text_widget.ensureCursorVisible()
        LOG.info(LOG.LOG_SOURCE.FE, f"Queue log: {safe_message}")

    @Slot(str)
    def _on_text_replace(self, message: str) -> None:
        """Overwrite the last line rather than appending after it.

        Same mechanics as `ProcessPage._on_text_update_replace_last_line`, so the
        two panes behave identically. Without it a "running..." line and its
        "done" replacement both stay in the log.
        """
        safe_message = scrub_secrets(message)
        cursor = self.text_widget.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(
            QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor
        )
        cursor.removeSelectedText()
        cursor.insertHtml(safe_message)
        self.text_widget.setTextCursor(cursor)
        self.text_widget.ensureCursorVisible()
        LOG.info(LOG.LOG_SOURCE.FE, f"Queue log replace last line: {safe_message}")

    @Slot(float)
    def _on_progress(self, value: float) -> None:
        self.progress_bar.setValue(int(value))

    @Slot(int, str)
    def _on_job_started(self, index: int, name: str) -> None:
        item = self._item(index)
        if item is None:
            return
        self._current_index = index
        item.setText(1, name)
        item.setText(2, "▶️ Running")
        item.setExpanded(True)
        self.job_tree.scrollToItem(item)
        # a new job's progress starts from zero, not wherever the previous
        # job's bar was left
        self.progress_bar.setValue(0)
        self.header_lbl.setText(
            f"<h3 style='margin: 0;'>Job {index} of {len(self.job_paths)}</h3>"
            f"<i><span>{escape(name)}</span></i>"
        )

    @Slot(str, str)
    def _on_tracker_status(self, tracker: str, status: str) -> None:
        """Record one tracker's status under the job currently running.

        Keyed on (job, tracker) rather than tracker alone. Trackers recur across
        jobs, and a tracker-only key would let the fourth job overwrite the
        first's result in place -- a status column that quietly describes the
        wrong release is worse than none.
        """
        parent = self._item(self._current_index)
        if parent is None:
            # status before any job announced itself; nothing to attach it to
            return

        key = (self._current_index, tracker)
        row = self._tracker_rows.get(key)
        if row is None:
            row = QTreeWidgetItem(("", tracker, status, ""))
            parent.addChild(row)
            parent.setExpanded(True)
            self._tracker_rows[key] = row
            return
        row.setText(2, status)

    @Slot(int, object)
    def _on_job_finished(self, index: int, outcome: QueuedJobOutcome) -> None:
        item = self._item(index)
        if item is None:
            return
        item.setText(1, outcome.job_name)
        item.setText(2, _RESULT_LABELS.get(outcome.result, outcome.result.name))
        disposition = _DISPOSITION_LABELS[outcome.disposition]
        detail = outcome.detail
        item.setText(
            3, f"{detail} — job {disposition}" if detail else f"Job {disposition}"
        )
        # A job that went through cleanly collapses to its one summary line; one
        # that did not stays open on the tracker that explains why. A long queue
        # then reads as a short list with the problems already unfolded.
        item.setExpanded(outcome.result is not QueuedJobResult.UPLOADED)

    @Slot(object)
    def _on_results(self, results: list[QueuedJobOutcome]) -> None:
        uploaded = sum(
            1 for outcome in results if outcome.result is QueuedJobResult.UPLOADED
        )
        self._on_text(
            f"<br /><h3 style='margin-bottom: 0;'>Queue finished: {uploaded} of "
            f"{len(results)} uploaded</h3>"
        )

    @Slot(str, str)
    def _on_failed(self, message: str, trace_back: str) -> None:
        LOG.error(LOG.LOG_SOURCE.FE, scrub_secrets(trace_back))
        self._on_text(f"<br /><p>{escape(message)}</p>")
        # Without this the job that was running when the queue itself raised
        # is left reading "Running" forever, under a header that already says
        # "Queue finished" -- the one row that most needs a correct status is
        # the one this leaves stuck.
        item = self._item(self._current_index)
        if item is not None:
            item.setText(2, _RESULT_LABELS[QueuedJobResult.FAILED])
            item.setText(3, escape(message))
            item.setExpanded(True)

    @Slot()
    def _on_cancel(self) -> None:
        if self._thread is None or not self._thread.isRunning():
            return
        self._thread.cancel()
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Finishing current job...")
        self._on_text(
            "<br /><span>Cancelling; the job currently uploading will finish "
            "first</span>"
        )

    @Slot()
    def _on_queue_finished(self) -> None:
        self._thread = None
        self.cancel_btn.hide()
        self.progress_bar.setValue(0)
        close_button = self.button_box.button(QDialogButtonBox.StandardButton.Close)
        if close_button:
            close_button.setEnabled(True)
            close_button.setDefault(True)
        self.header_lbl.setText("<h3 style='margin: 0;'>Queue finished</h3>")

    # ------------------------------------------------------------------
    def reject(self) -> None:
        """Refuse to close while a job is in flight.

        Closing the window would not stop the thread, so allowing it would leave
        uploads running with nothing showing them.
        """
        if self._thread is not None and self._thread.isRunning():
            if (
                QMessageBox.question(
                    self,
                    "Queue Running",
                    "The queue is still running. Stop it after the current job "
                    "finishes?",
                )
                is QMessageBox.StandardButton.Yes
            ):
                self._on_cancel()
            return
        super().reject()
