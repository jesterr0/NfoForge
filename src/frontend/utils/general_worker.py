from collections.abc import Callable
import traceback

from PySide6.QtCore import QObject, QThread, Signal

from src.logger.nfo_forge_logger import LOG


class GeneralWorker(QThread):
    """
    Handle jobs in a thread to keep the frontend smooth for different purposes.

    Connect to the signals:
    ```python
        job_finished = Signal(object)
        job_failed = Signal(str)
    ```
    """

    job_finished = Signal(object)
    job_failed = Signal(str)

    def __init__(
        self,
        func: Callable[..., object],
        parent: QObject | None = None,
        *func_args: object,
        **func_kwargs: object,
    ) -> None:
        super().__init__(parent=parent)
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
