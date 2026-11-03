"""Choosing where the data folder and plugins folder live, from Settings.

Both take effect on restart and only then. The running process has its paths,
its log, its loaded plugins and its open profile bound to the old folders, so
switching any of them part way would split one session's state across two
places.
"""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog, QWidget

from nfoforge.backend.utils.working_dir import normalise_path
from nfoforge.config.data_location import (
    DataDestination,
    RelocationError,
    check_data_destination,
    check_plugins_destination,
    copy_data,
    copy_plugins,
)
from nfoforge.config.paths import (
    AppPaths,
    DataLocation,
    DataLocationError,
    data_location_is_overridden,
    default_data_root,
    read_data_location,
    write_data_location,
)
from nfoforge.frontend.utils.app_lifecycle import restart_application

if TYPE_CHECKING:
    from nfoforge.frontend.windows.main_window import MainWindow


def _can_change_location(parent: QWidget) -> bool:
    if not data_location_is_overridden():
        return True
    QMessageBox.information(
        parent,
        "Folder Location",
        "This launch uses --data-dir, NFOFORGE_DATA_DIR, or a portable data "
        "folder, so saved folder choices do not apply. Restart without that "
        "override to change the folders in Settings.",
    )
    return False


def change_data_folder(
    parent: QWidget, paths: AppPaths, main_window: "MainWindow"
) -> None:
    """Ask for a new data folder, copy the data there, and restart into it."""
    if not _can_change_location(parent):
        return
    picked = QFileDialog.getExistingDirectory(
        parent, "Choose a folder for your NfoForge data", str(paths.state_root)
    )
    if not picked:
        return
    destination = Path(picked)

    try:
        kind = check_data_destination(paths, destination)
    except RelocationError as error:
        QMessageBox.warning(parent, "Data Folder", str(error))
        return

    if kind is DataDestination.EXISTING_DATA:
        question = (
            f"{destination} already holds NfoForge data.\n\n"
            "NfoForge will restart and use the data already there. Your current "
            f"data stays in {paths.state_root} and is not copied."
        )
    else:
        question = (
            f"Copy your data to {destination} and restart NfoForge using it?\n\n"
            "Profiles, templates, cookies, tools, logs and saved jobs are copied. "
            "Generated run output is not. Your current folder is left as it is, "
            "so you can remove it once you have checked the new one."
        )
    if (
        QMessageBox.question(parent, "Data Folder", question)
        is not QMessageBox.StandardButton.Yes
    ):
        return

    def finish() -> None:
        # The default folder is recorded as no choice at all, so moving back
        # leaves the same installation as never having moved.
        chosen = (
            None
            if normalise_path(destination) == normalise_path(default_data_root())
            else destination
        )
        _record_and_restart(
            parent, main_window, lambda current: replace(current, data_dir=chosen)
        )

    if kind is DataDestination.EXISTING_DATA:
        finish()
        return

    runner = _CopyRunner(
        parent,
        "Copying your data...",
        lambda progress: copy_data(paths.state_root, destination, progress),
    )
    runner.succeeded.connect(finish)
    runner.start()


def change_plugins_folder(
    parent: QWidget, paths: AppPaths, main_window: "MainWindow"
) -> None:
    """Ask for a new plugins folder, offering to copy installed plugins there."""
    if not _can_change_location(parent):
        return
    picked = QFileDialog.getExistingDirectory(
        parent, "Choose a folder for your plugins", str(paths.plugins)
    )
    if not picked:
        return
    destination = Path(picked)
    if normalise_path(destination) == normalise_path(paths.plugins):
        return

    try:
        check_plugins_destination(paths, destination)
    except RelocationError as error:
        QMessageBox.warning(parent, "Plugins Folder", str(error))
        return

    has_plugins = paths.plugins.is_dir() and any(paths.plugins.iterdir())
    is_empty = not any(destination.iterdir())
    copy_across = False
    if has_plugins and is_empty:
        answer = QMessageBox.question(
            parent,
            "Plugins Folder",
            f"Copy your installed plugins to {destination}?\n\n"
            "Plugin settings and credentials stay in your data folder either "
            "way. NfoForge restarts to load plugins from the new folder.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
        )
        if answer is QMessageBox.StandardButton.Cancel:
            return
        copy_across = answer is QMessageBox.StandardButton.Yes
    elif (
        QMessageBox.question(
            parent,
            "Plugins Folder",
            f"Load plugins from {destination}?\n\nNfoForge restarts to load "
            "plugins from the new folder. Plugins in the current folder are not "
            "copied.",
        )
        is not QMessageBox.StandardButton.Yes
    ):
        return

    def finish() -> None:
        # Choosing the plugins folder inside the data folder is the default, so
        # it is recorded as no choice -- and then follows the data if it moves.
        chosen = (
            None
            if normalise_path(destination)
            == normalise_path(paths.state_root / "plugins")
            else destination
        )
        _record_and_restart(
            parent, main_window, lambda current: replace(current, plugins_dir=chosen)
        )

    if not copy_across:
        finish()
        return

    runner = _CopyRunner(
        parent,
        "Copying your plugins...",
        lambda _progress: copy_plugins(paths.plugins, destination),
    )
    runner.succeeded.connect(finish)
    runner.start()


def _record_and_restart(
    parent: QWidget,
    main_window: "MainWindow",
    update: Callable[[DataLocation], DataLocation],
) -> None:
    """Write the new location, then restart so every path picks it up.

    The current location is read back rather than remembered, so changing one
    folder never resets the other. An unreadable file is replaced: the user
    has just said where they want things, which is more current than whatever
    the file failed to say.
    """
    try:
        current = read_data_location()
    except DataLocationError:
        current = DataLocation()
    try:
        write_data_location(update(current))
    except OSError as error:
        QMessageBox.critical(
            parent,
            "Folder Location",
            f"The new location could not be saved, so nothing changed.\n\n{error}",
        )
        return

    if not restart_application(main_window):
        QMessageBox.information(
            parent,
            "Folder Location",
            "The new location is saved. Restart NfoForge to start using it.",
        )


class _CopyWorker(QThread):
    progressed = Signal(str)
    failed = Signal(str)

    def __init__(
        self, copy: Callable[[Callable[[str], None]], None], parent: QObject
    ) -> None:
        super().__init__(parent)
        self._copy = copy

    def run(self) -> None:
        try:
            self._copy(self.progressed.emit)
        except RelocationError as error:
            self.failed.emit(str(error))
        except Exception as error:
            self.failed.emit(f"The copy failed: {error}")


class _CopyRunner(QObject):
    """Runs one copy behind a progress dialog, reporting success or failure.

    Threaded because the tools folder alone can take long enough that a window
    which stopped repainting would look like it had crashed. Parented to the
    calling widget so neither it nor its worker is collected mid-copy.
    """

    succeeded = Signal()

    def __init__(
        self,
        parent: QWidget,
        label: str,
        copy: Callable[[Callable[[str], None]], None],
    ) -> None:
        super().__init__(parent)
        self._parent_widget = parent
        self._failed = False
        self._progress = QProgressDialog(label, "", 0, 0, parent)
        # No cancel: stopping part way leaves a partial copy to reason about,
        # and nothing is deleted either way.
        self._progress.setCancelButton(None)
        self._progress.setWindowTitle("Folder Location")
        self._progress.setMinimumDuration(0)
        self._worker = _CopyWorker(copy, self)
        self._worker.progressed.connect(self._progress.setLabelText)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_finished)

    def start(self) -> None:
        self._worker.start()
        self._progress.show()

    def _on_failed(self, message: str) -> None:
        self._failed = True
        QMessageBox.warning(self._parent_widget, "Folder Location", message)

    def _on_finished(self) -> None:
        self._progress.close()
        if not self._failed:
            self.succeeded.emit()
        self.deleteLater()
