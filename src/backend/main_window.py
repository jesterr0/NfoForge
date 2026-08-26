from os import getpid
import sys
from typing import TYPE_CHECKING

from psutil import (
    NoSuchProcess as PNoSuchProcess,
    Process as PProcess,
    TimeoutExpired as PTimeOutExpired,
)
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from src.backend.utils.working_dir import IS_FROZEN

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


def kill_child_processes() -> None:
    """Use psutil to properly terminate and kill all child processes"""
    try:
        current_process = PProcess(getpid())
        children = current_process.children(recursive=True)
        if not children:
            return
        for child in children:
            try:
                child.terminate()
                child.wait(timeout=2)
            except PNoSuchProcess:
                continue
            except PTimeOutExpired:
                child.kill()
    except PNoSuchProcess:
        pass


def restart_application(main_window: "MainWindow") -> bool:
    """Close the main window (running its normal closeEvent teardown: flush
    debounced config save, kill_child_processes(), save window settings),
    relaunch a fresh NfoForge process with the same launch arguments, then
    quit this process's Qt event loop.

    `main_window.close()` is synchronous, so closeEvent's teardown (and its
    config writes) fully completes before we spawn the new process - the new
    process never races the old one's config write.

    Returns:
        bool: False without quitting if the window declined to close or the
        relaunch could not be started, True otherwise.
    """
    if not main_window.close():
        return False

    # frozen: sys.executable IS the app, so pass only the extra args.
    # source: sys.executable is python.exe, which needs the script path too.
    args = sys.argv[1:] if IS_FROZEN else sys.argv
    if not QProcess.startDetached(sys.executable, args):
        return False

    app = QApplication.instance()
    if app is not None:
        app.quit()
    return True
