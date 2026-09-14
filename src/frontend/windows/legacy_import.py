"""Importing a previous installation on demand, long after the first launch.

The same copying the migration does, offered from Settings so that declining it at
first run is not a decision a user is stuck with. It is deliberately not the same
entry point: the migration gates on the recorded layout version, correctly for a
one-time hop and wrongly for an action the user can take whenever they like.
"""

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog, QWidget

from src.config.layout_apply import (
    MigrationError,
    MigrationRun,
    import_legacy,
)
from src.config.layout_migration import LegacyInstall, recognise_legacy_install
from src.config.paths import AppPaths
from src.frontend.windows.migration_summary_dialog import MigrationSummaryDialog


def choose_legacy_install(parent: QWidget | None) -> LegacyInstall | None:
    """Ask for a folder and accept only one that holds settings.

    Shared with the first-launch prompt rather than written twice. Picking the
    wrong folder is easily done -- the one holding the application, not the
    nested data folder -- so a folder with nothing in it says so instead of
    being accepted and quietly importing nothing.
    """
    picked = QFileDialog.getExistingDirectory(
        parent, "Select your previous NfoForge folder"
    )
    if not picked:
        return None

    found = recognise_legacy_install(Path(picked))
    if found is None:
        QMessageBox.information(
            parent,
            "Nothing to import there",
            f"No NfoForge settings were found in:\n\n{picked}\n\n"
            "Choose the folder you extracted NfoForge into, the one holding the "
            "application itself.",
        )
    return found


class LegacyImportWorker(QThread):
    """Copies a previous installation in, off the GUI thread.

    Threaded because a hand-assembled toolchain can be large enough that the
    copy takes minutes, and a window that stops repainting for that long is
    indistinguishable from one that has crashed.
    """

    progressed = Signal(str)
    completed = Signal(object)  # MigrationRun
    failed = Signal(str)

    def __init__(
        self,
        paths: AppPaths,
        legacy: LegacyInstall,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.paths = paths
        self.legacy = legacy

    def run(self) -> None:
        try:
            self.completed.emit(
                import_legacy(self.paths, self.legacy, progress=self.progressed.emit)
            )
        except MigrationError as error:
            self.failed.emit(
                "The import did not finish. Nothing was deleted, and your "
                "previous installation is unchanged.\n\n"
                f"{error}"
            )
        except Exception as error:
            self.failed.emit(f"The import failed: {error}")


class LegacyImportRunner(QObject):
    """Runs one import and reports it, keeping its worker alive until it ends.

    An object rather than a function because the worker and its progress dialog
    have to outlive the call that starts them. A local variable would be
    collected the moment the call returned, taking the running thread with it.
    """

    def __init__(self, paths: AppPaths, parent: QWidget) -> None:
        super().__init__(parent)
        self._paths = paths
        self._parent_widget = parent
        self._worker: LegacyImportWorker | None = None
        self._progress: QProgressDialog | None = None

    def start(self, legacy: LegacyInstall) -> None:
        self._progress = QProgressDialog(
            "Importing your previous installation...",
            "",
            0,
            0,
            self._parent_widget,
        )
        # No cancel button: the copy is mid-flight and stopping it part way would
        # leave a partial copy the user then has to reason about. Nothing is
        # deleted either way, so letting it finish is the cheaper outcome.
        self._progress.setCancelButton(None)
        self._progress.setWindowTitle("Import")
        self._progress.setMinimumDuration(0)

        self._worker = LegacyImportWorker(self._paths, legacy, self)
        self._worker.progressed.connect(self._progress.setLabelText)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._progress.close)
        self._worker.start()
        self._progress.show()

    def _on_completed(self, run: MigrationRun) -> None:
        summary = MigrationSummaryDialog(
            run.plan,
            run.outcome,
            missing_profile=run.missing_profile,
            parent=self._parent_widget,
        )
        summary.exec()
        summary.deleteLater()

    def _on_failed(self, message: str) -> None:
        QMessageBox.warning(self._parent_widget, "Import", message)
