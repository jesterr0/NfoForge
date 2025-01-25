from collections.abc import Sequence
from pathlib import Path
from pymediainfo import MediaInfo
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Slot, Signal
from PySide6.QtWidgets import (
    QToolButton,
    QLineEdit,
    QLabel,
    QFileDialog,
    QVBoxLayout,
    QMessageBox,
)

from src.backend.media_input import MediaInputBackEnd
from src.config.config import Config
from src.enums.media_mode import MediaMode
from src.exceptions import MediaFileNotFoundError
from src.frontend.global_signals import GSigs
from src.frontend.custom_widgets.dnd_factory import DNDLineEdit
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.frontend.utils import build_auto_theme_icon_buttons
from src.frontend.utils.media_input_utils import MediaInputWorker

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class MediaInputBasic(BaseWizardPage):
    file_loaded = Signal(str)

    def __init__(self, config: Config, parent: "MainWindow | Any") -> None:
        super().__init__(config, parent)

        self.setObjectName("mediaInputBasic")
        self.setTitle("Input")
        self.setCommitPage(True)

        self.config = config
        self.backend = MediaInputBackEnd()
        self.worker: MediaInputWorker | None = None
        self._loading_completed = False

        self.extensions = self.get_media_extensions()

        self.input_label = QLabel("Input", self)
        self.input_entry = DNDLineEdit(self)
        self.input_entry.setReadOnly(True)
        self.input_entry.set_extensions(self.extensions)
        self.input_entry.dropped.connect(
            lambda e: self.update_entries(e, self.input_entry)
        )
        self.media_button: QToolButton = build_auto_theme_icon_buttons(
            QToolButton, "open.svg", "mediaButton", 24, 24, parent=self
        )
        self.media_button.clicked.connect(
            lambda: self.open_media_dialog(self.input_entry, "media", self.extensions)
        )

        self.media_dir_button: QToolButton = build_auto_theme_icon_buttons(
            QToolButton, "open_folder.svg", "mediaButton", 24, 24, parent=self
        )
        self.media_dir_button.clicked.connect(
            lambda: self.open_dir_dialog(self.input_entry)
        )

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addLayout(
            self._button_form_layout(
                self.input_label,
                self.input_entry,
                self.media_button,
                self.media_dir_button,
            )
        )
        self._toggle_dir_input()

    def validatePage(self) -> bool:
        if self._loading_completed:
            return True

        required_entries = [
            self.input_entry,
        ]
        invalid_entries = False

        for entry in required_entries:
            if entry.text().strip() == "" or entry.text() == entry.placeholderText():
                invalid_entries = True
                # TODO: Flash red or something once we theme it
                # entry.setStyleSheet("QLineEdit {border: 1px solid red; border-radius: 3px;}")
                entry.setPlaceholderText("Requires input")

        if invalid_entries:
            return False
        else:
            try:
                self.update_payload_data()
            except MediaFileNotFoundError as input_error:
                required_entries[0].setPlaceholderText(str(input_error))
            return False

    def update_payload_data(self) -> None:
        entry_data = Path(self.input_entry.text())
        if self.config.cfg_payload.media_mode == MediaMode.MOVIES:
            if entry_data.is_file():
                self.config.media_input_payload.encode_file = (
                    Path(entry_data) if entry_data else None
                )
            elif entry_data.is_dir():
                media_file = self.find_largest_media(entry_data, self.extensions)
                if not media_file:
                    raise MediaFileNotFoundError("Cannot detect media file")
                self.config.media_input_payload.encode_file = media_file
                self.config.media_input_payload.encode_file_dir = entry_data
            self._run_worker()
        elif self.config.cfg_payload.media_mode == MediaMode.SERIES:
            # TODO: add support for SERIES
            raise NotImplementedError("No support for series yet")

    def _run_worker(self) -> None:
        file_path = self.config.media_input_payload.encode_file
        if not file_path:
            raise FileNotFoundError("Failed to detect input path")
        self.worker = MediaInputWorker(
            func=self.backend.get_media_info, file_input=file_path
        )
        self.worker.job_failed.connect(self._worker_failed)
        self.worker.job_finished.connect(self._worker_finished)
        GSigs().main_window_set_disabled.emit(True)
        GSigs().main_window_update_status_tip.emit("Parsing MediaInfo", 0)
        self.worker.start()

    @Slot(object)
    def _worker_finished(self, mi_obj: MediaInfo | None) -> None:
        if not mi_obj or (mi_obj and not isinstance(mi_obj, MediaInfo)):
            raise AttributeError("Failed to detect MediaInfo")
        self.config.media_input_payload.encode_file_mi_obj = mi_obj
        self._loading_completed = True
        GSigs().main_window_set_disabled.emit(False)
        GSigs().main_window_clear_status_tip.emit()
        GSigs().wizard_next.emit()

    @Slot(str)
    def _worker_failed(self, msg: str) -> None:
        QMessageBox.critical(self, "Error", msg)
        self._loading_completed = False
        GSigs().main_window_set_disabled.emit(False)

    @Slot()
    def open_media_dialog(
        self, entry_widget: QLineEdit, title: str, extension: list | set
    ) -> None:
        supported_extensions = (
            f"{title} file " f"({' '.join(['*' + ext for ext in extension])})"
        )
        open_file, _ = QFileDialog.getOpenFileName(
            parent=self,
            caption=f"Open {title.title()} File",
            filter=supported_extensions,
        )
        if open_file:
            self.update_entries((str(Path(open_file)),), entry_widget)

    @Slot()
    def open_dir_dialog(self, entry_widget: QLineEdit) -> None:
        open_dir = QFileDialog.getExistingDirectory(
            parent=self,
            caption="Select Directory",
        )
        if open_dir:
            entry_widget.setText(str(Path(open_dir)))

    def get_media_extensions(self) -> Sequence[str]:
        accepted_inputs = self.config.cfg_payload.source_media_ext_filter
        if (
            accepted_inputs
            and isinstance(accepted_inputs, list)
            and len(accepted_inputs) > 0
        ):
            for item in accepted_inputs:
                if item not in self.config.ACCEPTED_EXTENSIONS:
                    QMessageBox.warning(
                        self,
                        "Extension Error",
                        f"Extension {item} is not valid, using defaults...",
                    )
                    return self.config.ACCEPTED_EXTENSIONS
            return accepted_inputs
        return self.config.ACCEPTED_EXTENSIONS

    def _toggle_dir_input(self) -> None:
        if self.config.cfg_payload.media_input_dir:
            self.media_dir_button.show()
            self.input_entry.set_accept_dir(True)
        else:
            self.media_dir_button.hide()
            self.input_entry.set_accept_dir(False)

    def update_entries(self, event: Sequence, widget: QLineEdit) -> None:
        file_path = str(Path(event[0]))
        widget.setText(file_path)
        self.file_loaded.emit(file_path)

    @Slot()
    def reset_page(self) -> None:
        self.input_entry.clear()
        self.input_entry.setPlaceholderText("")
        self._toggle_dir_input()
        self.worker = None
        self._loading_completed = False
