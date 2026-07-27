from collections.abc import Callable
import traceback
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from src.logger.nfo_forge_logger import LOG


class MainWindowWorker(QThread):
    """
    Threaded worker to execute methods/functions that might need to be done
    from the main window to keep the UI smooth.
    """

    job_finished = Signal(object)
    job_failed = Signal(str)

    def __init__(
        self,
        func: Callable[..., str | None],
        func_args: tuple[Any, ...] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.func = func
        self.func_args = func_args

    def run(self) -> None:
        try:
            if not self.func_args:
                job = self.func()
            else:
                job = self.func(*self.func_args)

            if job:
                self.job_failed.emit(job)
        except Exception as e:
            LOG.critical(
                LOG.LOG_SOURCE.FE,
                f"Failed to clean up log directory {e}\n({traceback.format_exc()})",
            )
            self.job_failed.emit(str(e))
