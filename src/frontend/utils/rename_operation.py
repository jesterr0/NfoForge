from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from src.backend.rename_files import RenameExecutor, RenamePlan, RenameResult
from src.frontend.global_signals import GSigs
from src.frontend.utils.general_worker import GeneralWorker


class RenameOperationController(QObject):
    """Own the worker and guarantee UI cleanup for every terminal outcome."""

    completed = Signal(object)

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._worker: GeneralWorker | None = None
        self._input_path: Path | None = None

    @property
    def is_running(self) -> bool:
        return self._worker is not None

    def start(self, plan: RenamePlan, status_text: str) -> bool:
        if self.is_running:
            return False

        self._input_path = plan.input_path
        self._worker = GeneralWorker(
            func=RenameExecutor.execute,
            parent=self,
            plan=plan,
        )
        self._worker.job_finished.connect(self._on_finished)
        self._worker.job_failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_thread_finished)

        GSigs().main_window_set_disabled.emit(True)
        GSigs().main_window_update_status_tip.emit(status_text, 0)
        self._worker.start()
        return True

    @Slot(object)
    def _on_finished(self, result: object) -> None:
        if not isinstance(result, RenameResult):
            self._finish(
                RenameResult(
                    success=False,
                    path_mapping={},
                    updated_input_path=self._input_path,
                    message="The rename worker returned an invalid result.",
                )
            )
            return
        self._finish(result)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._finish(
            RenameResult(
                success=False,
                path_mapping={},
                updated_input_path=self._input_path,
                message=message,
            )
        )

    def _finish(self, result: RenameResult) -> None:
        GSigs().main_window_set_disabled.emit(False)
        GSigs().main_window_clear_status_tip.emit()

        self._input_path = None
        self.completed.emit(result)

    @Slot()
    def _on_thread_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
