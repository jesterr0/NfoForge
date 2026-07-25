"""What survives a crash that Python and Qt never get to report.

`sys.excepthook` needs a Python exception and `qt_message_handler` needs Qt to
emit a message. A segfault or access violation inside Qt or its bindings
produces neither: the process disappears with an empty log, which is the worst
possible bug report. `faulthandler` hooks the fatal signals themselves and is
the only thing that leaves a Python stack behind.

The other half is the fatal Qt message. Qt calls the message handler and then
aborts regardless, so whatever the handler does has to finish first - and
opening a modal dialog there runs a nested event loop in a process that is
already going down.

`start_ui.NfoForge` drives real Qt widgets that aren't worth standing up for
this, so these build a bare instance via `object.__new__` as the sibling
startup tests do.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QtMsgType

import start_ui


def _bare_nfoforge() -> start_ui.NfoForge:
    app = object.__new__(start_ui.NfoForge)
    app.splash_screen = None
    app.main_window = None
    return app


def test_a_fatal_qt_message_is_logged_without_opening_a_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`QtFatalMsg` means Qt is about to `abort()`. `_error_message_box` runs
    `exec()`, so the handler would open a modal dialog and spin a nested event
    loop in a process that is already tearing down - it can hang or die before
    anyone reads it. The message still has to reach the log, which is what the
    crash report is actually built from.
    """
    app = _bare_nfoforge()
    dialogs = []
    app._error_message_box = lambda *args, **kwargs: dialogs.append(args)
    logged = []
    monkeypatch.setattr(
        start_ui.LOG, "critical", lambda _source, message: logged.append(message)
    )

    app.qt_message_handler(
        QtMsgType.QtFatalMsg, None, "QThread: Destroyed while thread is still running"
    )

    assert dialogs == []
    assert any("QThread: Destroyed" in message for message in logged)


def test_a_qt_warning_still_opens_a_dialog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the fatal case is about to abort; a warning or critical message
    leaves a working application, so it keeps the dialog it always had.
    """
    app = _bare_nfoforge()
    dialogs = []
    app._error_message_box = lambda *args, **kwargs: dialogs.append(args)
    monkeypatch.setattr(start_ui.LOG, "critical", lambda _source, _message: None)

    app.qt_message_handler(QtMsgType.QtWarningMsg, None, "something is off")

    assert len(dialogs) == 1


def test_the_crash_log_handle_is_kept_open_for_the_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`faulthandler` writes to the file descriptor while the process is dying,
    so the handle must outlive this call. Letting it be closed or collected
    would leave the dump writing to nothing, which is the same as not having it.
    """
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(start_ui.LOG, "log_file", logs / "nfoforge_run.log")
    enabled = {}
    monkeypatch.setattr(
        start_ui.faulthandler, "enable", lambda file: enabled.update(file=file)
    )
    app = _bare_nfoforge()

    app._enable_crash_dump()

    assert enabled["file"] is app._crash_log_handle
    assert not app._crash_log_handle.closed
    app._crash_log_handle.close()


def test_the_crash_log_names_the_run_it_belongs_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The log file is per-run but the crash log is appended across runs, so a
    dump is unattributable without something tying it to that run's log.
    """
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(start_ui.LOG, "log_file", logs / "nfoforge_run.log")
    monkeypatch.setattr(start_ui.faulthandler, "enable", lambda file: None)
    app = _bare_nfoforge()

    app._enable_crash_dump()
    app._crash_log_handle.close()

    assert "nfoforge_run.log" in (logs / "crash.log").read_text(encoding="utf-8")


def test_an_unwritable_crash_log_does_not_stop_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Diagnostics are not worth failing a launch over: a read-only install
    directory must cost the dump, not the application.
    """
    monkeypatch.setattr(
        start_ui.LOG, "log_file", tmp_path / "nonexistent" / "nfoforge_run.log"
    )
    warnings = []
    monkeypatch.setattr(
        start_ui.LOG, "warning", lambda _source, message: warnings.append(message)
    )
    app = _bare_nfoforge()

    app._enable_crash_dump()

    assert warnings
