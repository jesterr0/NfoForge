import traceback
from collections.abc import Callable

from PySide6.QtCore import Signal, QThread
from src.logger.nfo_forge_logger import LOG


class MediaInputWorker(QThread):
    """Handle jobs in a thread to keep the frontend smooth for media input"""

    job_finished = Signal(object)
    job_failed = Signal(str)

    def __init__(self, func: Callable, *func_args, **func_kwargs) -> None:
        super().__init__()
        self.func = func
        self.func_args = func_args
        self.func_kwargs = func_kwargs

    def run(self) -> None:
        try:
            job = self.func(*self.func_args, **self.func_kwargs)
            self.job_finished.emit(job)
        except Exception as e:
            LOG.error(LOG.LOG_SOURCE.FE, traceback.format_exc())
            self.job_failed.emit(f"Error: Please check logs for more details ({e})")
