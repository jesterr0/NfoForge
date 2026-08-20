"""What survives a crash that Python and Qt never get to report.

`sys.excepthook` needs a Python exception and `qt_message_handler` needs Qt to
emit a message. A segfault or access violation inside Qt or its bindings
produces neither: the process disappears with an empty log, which is the worst
possible bug report. `faulthandler` hooks the fatal signals themselves and is
the only thing that leaves a Python stack behind.

The other half is the Qt message handler, and what it is allowed to do. Qt
calls it on the thread that emitted the message - including its own network
thread - and after a fatal one it aborts regardless. So the handler must never
build a widget (a cross-thread parent, then a nested modal event loop off the
GUI thread, which wedges the process), and after a fatal message it must not
open a dialog at all in a process that is already going down.

`start_ui.NfoForge` drives real Qt widgets that aren't worth standing up for
this, so these build a bare instance via `object.__new__` as the sibling
startup tests do.
"""

from pathlib import Path
import threading
from types import SimpleNamespace

from PySide6.QtCore import QThread, QtMsgType
import pytest

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


def test_a_qt_warning_is_logged_without_a_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qt warns about plenty of benign things - pooled TLS sockets being
    retired, layout quibbles, deprecations. A modal dialog for each of those
    interrupts the user over nothing, so a warning is a log line and no more.
    Real faults still arrive as critical or fatal.
    """
    app = _bare_nfoforge()
    dialogs = []
    app._error_message_box = lambda *args, **kwargs: dialogs.append(args)
    warnings = []
    monkeypatch.setattr(
        start_ui.LOG, "warning", lambda _source, message: warnings.append(message)
    )

    app.qt_message_handler(
        QtMsgType.QtWarningMsg, None, "QIODevice::read (QSslSocket): device not open"
    )

    assert dialogs == []
    assert any("QSslSocket" in message for message in warnings)


def test_a_qt_critical_message_opens_a_dialog(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fatal case is about to abort and a warning is noise, but a critical
    message leaves a working application with a real problem in it, so it keeps
    the dialog.
    """
    app = _bare_nfoforge()
    dialogs = []
    app._error_message_box = lambda *args, **kwargs: dialogs.append(args)
    monkeypatch.setattr(start_ui.LOG, "critical", lambda _source, _message: None)

    app.qt_message_handler(QtMsgType.QtCriticalMsg, None, "something is off")

    assert len(dialogs) == 1


def test_a_qt_message_records_the_thread_that_emitted_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qt calls the handler on the emitting thread, so the thread name is what
    separates a benign message from the GUI thread from one raised on a worker
    or on Qt's own network thread. Without it the two read identically in a log
    and there is nothing to diagnose from.
    """
    app = _bare_nfoforge()
    app._error_message_box = lambda *args, **kwargs: None
    logged = []
    monkeypatch.setattr(
        start_ui.LOG, "critical", lambda _source, message: logged.append(message)
    )

    app.qt_message_handler(QtMsgType.QtCriticalMsg, None, "something is off")

    assert any(threading.current_thread().name in message for message in logged)


def test_an_off_gui_thread_error_is_handed_to_the_relay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression this guards.

    Qt calls the message handler on whichever thread emitted the message, and
    `sys.excepthook` is no better behaved. Building `ScrollableErrorDialog`
    there parents a widget across threads - Qt warns `QObject::setParent`,
    which re-enters the handler - and `exec()` then spins a nested modal event
    loop off the GUI thread, wedging the process. An off-thread request has to
    leave via the relay instead, and construct nothing.
    """
    app = _bare_nfoforge()
    shown = []
    app._show_error_dialog = lambda *args: shown.append(args)
    emitted = []
    app._gui_relay = SimpleNamespace(
        show_error=SimpleNamespace(emit=lambda *args: emitted.append(args))
    )
    # a thread object that is deliberately not the caller's
    app.app = SimpleNamespace(thread=lambda: object())

    app._error_message_box("QtError", "device not open")

    assert shown == []
    assert emitted == [("QtError", "device not open", "")]


def test_a_gui_thread_error_still_opens_the_dialog_synchronously() -> None:
    """Deferring every call would change startup: `_handle_config_error` and
    its siblings run before `app.exec()` and rely on `exec()` blocking before
    they continue. Only genuinely off-thread callers get marshalled.
    """
    app = _bare_nfoforge()
    shown = []
    app._show_error_dialog = lambda *args: shown.append(args)
    app._gui_relay = SimpleNamespace(
        show_error=SimpleNamespace(
            emit=lambda *args: pytest.fail("a GUI-thread call must not be deferred")
        )
    )
    app.app = SimpleNamespace(thread=QThread.currentThread)

    app._error_message_box("Config Error", "bad toml", "a traceback")

    assert shown == [("Config Error", "bad toml", "a traceback")]


def test_a_second_dialog_is_suppressed_while_one_is_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stacking modals buries the window until every one is dismissed, which
    reads as a lockup, and it is also what would recurse if building the dialog
    emitted a Qt message of its own.
    """
    app = _bare_nfoforge()
    app._error_dialog_active = True
    built = []
    monkeypatch.setattr(
        start_ui, "ScrollableErrorDialog", lambda *a, **kw: built.append(a)
    )
    monkeypatch.setattr(start_ui.LOG, "error", lambda _source, _message: None)

    app._show_error_dialog("QtError", "second one", "")

    assert built == []


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
