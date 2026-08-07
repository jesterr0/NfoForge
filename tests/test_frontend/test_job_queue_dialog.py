"""Coverage for the queue's own window.

The queue does not borrow the process page, so what is tested here is the state
machine that replaced it: a cancel that reaches the runner, a close that cannot
happen mid-run, and a summary that reports what became of each job.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PySide6.QtWidgets import QDialogButtonBox, QMessageBox
import pytest

from src.backend.job_queue import JobDisposition, QueuedJobOutcome, QueuedJobResult
from src.frontend.custom_widgets.job_queue_dialog import JobQueueDialog


@pytest.fixture
def dialog(qapp: Any, tmp_path: Path) -> JobQueueDialog:
    """A dialog that has not been started.

    `start()` is deliberately separate from construction, so building this
    dialog never touches `ProcessBackEnd` or spins up a real `_QueueThread` --
    no config or monkeypatching needed. Tests exercise its slots directly, the
    same way the queue's own worker thread would call them.
    """
    return JobQueueDialog(
        job_paths=[tmp_path / "jobs" / "one", tmp_path / "jobs" / "two"],
        config=SimpleNamespace(),
    )


def test_every_job_gets_a_row_up_front(dialog: JobQueueDialog) -> None:
    assert dialog.job_tree.topLevelItemCount() == 2
    assert dialog.job_tree.topLevelItem(0).text(0) == "1"


def test_a_started_job_is_marked_running(dialog: JobQueueDialog) -> None:
    dialog._on_job_started(1, "Example (2024)")

    item = dialog.job_tree.topLevelItem(0)
    assert item.text(1) == "Example (2024)"
    assert "Running" in item.text(2)


def test_tracker_status_lands_under_the_running_job(dialog: JobQueueDialog) -> None:
    dialog._on_job_started(1, "Example")

    dialog._on_tracker_status("Aither", "▶️ Processing")

    parent = dialog.job_tree.topLevelItem(0)
    assert parent.childCount() == 1
    assert parent.child(0).text(1) == "Aither"
    assert parent.child(0).text(2) == "▶️ Processing"


def test_a_repeated_status_updates_the_row_rather_than_adding_one(
    dialog: JobQueueDialog,
) -> None:
    dialog._on_job_started(1, "Example")
    dialog._on_tracker_status("Aither", "▶️ Processing")

    dialog._on_tracker_status("Aither", "✅ Complete")

    parent = dialog.job_tree.topLevelItem(0)
    assert parent.childCount() == 1
    assert parent.child(0).text(2) == "✅ Complete"


def test_the_same_tracker_in_two_jobs_gets_two_rows(dialog: JobQueueDialog) -> None:
    """The flat tracker tree could not do this: one row, last write wins."""
    dialog._on_job_started(1, "First")
    dialog._on_tracker_status("Aither", "✅ Complete")
    dialog._on_job_started(2, "Second")
    dialog._on_tracker_status("Aither", "❌ Failed")

    assert dialog.job_tree.topLevelItem(0).child(0).text(2) == "✅ Complete"
    assert dialog.job_tree.topLevelItem(1).child(0).text(2) == "❌ Failed"


def test_tracker_status_before_any_job_starts_is_ignored(
    dialog: JobQueueDialog,
) -> None:
    dialog._on_tracker_status("Aither", "▶️ Processing")

    assert dialog.job_tree.topLevelItem(0).childCount() == 0


def test_a_clean_job_collapses_and_a_problem_job_stays_open(
    dialog: JobQueueDialog, tmp_path: Path
) -> None:
    """A finished queue should read as a short list with the problems opened."""
    dialog._on_job_started(1, "Clean")
    dialog._on_tracker_status("Aither", "✅ Complete")
    dialog._on_job_finished(
        1,
        QueuedJobOutcome(
            job_name="Clean", path=tmp_path, result=QueuedJobResult.UPLOADED
        ),
    )
    dialog._on_job_started(2, "Broken")
    dialog._on_tracker_status("Huno", "❌ Failed")
    dialog._on_job_finished(
        2,
        QueuedJobOutcome(
            job_name="Broken", path=tmp_path, result=QueuedJobResult.FAILED
        ),
    )

    assert not dialog.job_tree.topLevelItem(0).isExpanded()
    assert dialog.job_tree.topLevelItem(1).isExpanded()


def test_a_finished_job_reports_its_result_and_disposition(
    dialog: JobQueueDialog, tmp_path: Path
) -> None:
    dialog._on_job_finished(
        1,
        QueuedJobOutcome(
            job_name="Example",
            path=tmp_path,
            result=QueuedJobResult.UPLOADED,
            disposition=JobDisposition.DELETED,
        ),
    )

    item = dialog.job_tree.topLevelItem(0)
    assert "Uploaded" in item.text(2)
    assert "removed" in item.text(3).lower()


def test_cancelling_asks_the_thread_to_stop(dialog: JobQueueDialog) -> None:
    stopped: list[bool] = []
    dialog._thread = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        isRunning=lambda: True, cancel=lambda: stopped.append(True)
    )

    dialog._on_cancel()

    assert stopped == [True]
    assert not dialog.cancel_btn.isEnabled()


def test_the_dialog_refuses_to_close_while_a_job_is_in_flight(
    dialog: JobQueueDialog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Answering "stop it" cancels the run; it must not also close the window.

    `dialog.result()` can't be trusted to prove that on its own: `Rejected` and
    a dialog's untouched default result are both `0`, so a check against
    `result()` alone passes whether or not `reject()` ever ran (see the
    companion test below, where the real value the class actually produces is
    pinned down). Spying on `done()` -- the method `QDialog.reject()` calls
    internally to actually close -- is what tells "refused" apart from
    "closed", regardless of what `result()` reads.
    """
    stopped: list[bool] = []
    dialog._thread = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        isRunning=lambda: True, cancel=lambda: stopped.append(True)
    )
    done_calls: list[object] = []
    monkeypatch.setattr(dialog, "done", lambda *args: done_calls.append(args))
    # answering "Yes" (stop it) is the harder case: it must still stop short
    # of actually closing, only asking the thread to cancel
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
    )

    dialog.reject()

    assert stopped == [True]
    assert done_calls == []
    assert dialog._thread is not None


def test_the_dialog_closes_when_nothing_is_running(
    dialog: JobQueueDialog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The companion to the refusal above: with no job in flight, `reject()`
    must still close rather than refusing unconditionally."""
    dialog._thread = None
    done_calls: list[object] = []
    monkeypatch.setattr(dialog, "done", lambda *args: done_calls.append(args))

    dialog.reject()

    assert done_calls == [(int(JobQueueDialog.DialogCode.Rejected),)]


def test_a_known_secret_does_not_survive_into_the_log(
    dialog: JobQueueDialog,
) -> None:
    """`_on_text` carries tracker responses, which can carry credentials --
    the same reason `ProcessPage._on_text_update` scrubs before inserting."""
    dialog._on_text(
        "<span>https://tracker.example/deadbeefdeadbeefdeadbeefdeadbeef/announce</span>"
    )

    assert "deadbeefdeadbeefdeadbeefdeadbeef" not in dialog.text_widget.toPlainText()


def test_replacing_the_last_line_scrubs_too_and_leaves_one_line(
    dialog: JobQueueDialog,
) -> None:
    """The replace path is scrubbed the same as the append path -- unlike
    `ProcessPage`'s equivalent, which does not -- because it carries the same
    tracker responses and is if anything the more exposed of the two. This
    also guards the overwrite mechanic itself: the line being replaced must
    not survive alongside its replacement.
    """
    dialog._on_text("<span>running...</span>")

    dialog._on_text_replace(
        "<span>done: https://tracker.example/"
        "deadbeefdeadbeefdeadbeefdeadbeef/announce</span>"
    )

    text = dialog.text_widget.toPlainText()
    assert "deadbeefdeadbeefdeadbeefdeadbeef" not in text
    assert "running" not in text
    assert text.count("\n") == 0


def test_a_crash_marks_the_running_job_as_failed_rather_than_leaving_it_stuck(
    dialog: JobQueueDialog,
) -> None:
    """Without this the job that was running when the queue itself raised is
    left reading "Running" under a header that already says "Queue finished".
    """
    dialog._on_job_started(1, "Example")

    dialog._on_failed("boom", "traceback text")

    item = dialog.job_tree.topLevelItem(0)
    assert "Failed" in item.text(2)


def test_the_dialog_closes_once_the_queue_is_done(dialog: JobQueueDialog) -> None:
    dialog._thread = None
    dialog._on_queue_finished()

    assert dialog.cancel_btn.isHidden()
    assert dialog.button_box.button(QDialogButtonBox.StandardButton.Close).isEnabled()
