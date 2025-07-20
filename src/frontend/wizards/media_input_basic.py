from collections.abc import Sequence
from pathlib import Path
from typing import Any, TYPE_CHECKING

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
)
from pymediainfo import MediaInfo

from src.backend.media_input import MediaInputBackEnd
from src.backend.utils.file_utilities import generate_unique_date_name
from src.config.config import Config
from src.enums.media_mode import MediaMode
from src.exceptions import MediaFileNotFoundError
from src.frontend.custom_widgets.dnd_factory import DNDLineEdit
from src.frontend.custom_widgets.file_tree import FileSystemTreeView
from src.frontend.global_signals import GSigs
from src.frontend.utils import QWidgetTempStyle, build_auto_theme_icon_buttons
from src.frontend.utils.media_input_utils import MediaInputWorker
from src.frontend.wizards.wizard_base_page import BaseWizardPage

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class MediaInputBasic(BaseWizardPage):
    DEF_INPUT_ENTRY_TXT = "Open file or directory..."

    file_loaded = Signal(str)

    def __init__(self, config: Config, parent: "MainWindow | Any") -> None:
        super().__init__(config, parent)

        self.setObjectName("mediaInputBasic")
        self.setTitle("Input")
        self.setCommitPage(True)

        self.backend = MediaInputBackEnd()
        self.worker: MediaInputWorker | None = None
        self._loading_completed = False

        self.extensions = self.get_media_extensions()

        self.input_entry: QLineEdit = DNDLineEdit(
            parent=self, readOnly=True, placeholderText=self.DEF_INPUT_ENTRY_TXT
        )
        self.input_entry.set_extensions(self.extensions)
        self.input_entry.set_accept_dir(True)
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

        self.file_tree = FileSystemTreeView(parent=self)
        self.file_tree.hide()

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addWidget(self.input_entry, stretch=1)
        button_layout.addWidget(self.media_button)
        button_layout.addWidget(self.media_dir_button)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addLayout(button_layout)
        self.main_layout.addWidget(self.file_tree, stretch=1)
        self.main_layout.addStretch()

    def validatePage(self) -> bool:
        if self._loading_completed:
            super().validatePage()
            return True

        required_entries = [
            self.input_entry,
        ]
        invalid_entries = False

        for entry in required_entries:
            if entry.text().strip() == "" or entry.text() == entry.placeholderText():
                invalid_entries = True
                entry.setPlaceholderText("Requires input")
                QWidgetTempStyle().set_temp_style(widget=entry, system_beep=True)

        if invalid_entries:
            return False
        else:
            try:
                self.update_payload_data()
            except MediaFileNotFoundError as input_error:
                # directory
                if self.file_tree.isVisible():
                    QMessageBox.warning(self, "Error", str(input_error))
                    self.reset_page()
                # single file
                else:
                    required_entries[0].setPlaceholderText(str(input_error))
            return False

    def update_payload_data(self) -> None:
        entry_data = Path(self.input_entry.text())
        if self.config.cfg_payload.media_mode == MediaMode.MOVIES:
            # handle file
            if entry_data.is_file():
                self.config.media_input_payload.encode_file = (
                    Path(entry_data) if entry_data else None
                )
            # handle directory
            elif entry_data.is_dir():
                checked_items: list[dict[str, Any]] = (
                    self.file_tree.get_checked_items() or []
                )
                supported_files: list[dict[str, Any]] = [
                    item
                    for item in checked_items
                    if isinstance(item, dict)
                    and not item.get("is_dir", False)
                    and Path(item.get("path", "")).suffix.lower()
                    in self.config.cfg_payload.source_media_ext_filter
                ]
                if not supported_files:
                    raise MediaFileNotFoundError(
                        "No supported media files selected in directory "
                        f"({', '.join(self.config.cfg_payload.source_media_ext_filter)})"
                    )
                largest_file = max(supported_files, key=lambda x: x.get("size", 0))
                self.config.media_input_payload.encode_file = Path(largest_file["path"])
                self.config.media_input_payload.encode_file_dir = entry_data
            self._run_worker()
        elif self.config.cfg_payload.media_mode == MediaMode.SERIES:
            # TODO: add support for SERIES
            raise NotImplementedError("No support for series yet")

    def _run_worker(self) -> None:
        file_path = self.config.media_input_payload.encode_file
        if not file_path:
            raise FileNotFoundError("Failed to detect input path")
        self.set_working_dir(
            self.config.cfg_payload.working_dir
            / generate_unique_date_name(file_path.stem)
        )
        self.worker = MediaInputWorker(
            func=self.backend.get_media_info, file_input=file_path, parent=self
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
            f"{title} file ({' '.join(['*' + ext for ext in extension])})"
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
            self.update_entries((str(Path(open_dir)),), entry_widget)

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

    def update_entries(self, event: Sequence, widget: QLineEdit) -> None:
        path = Path(event[0])

        # enable file tree if directory
        if path.is_dir():
            self.file_tree.build_tree(path)
            self.file_tree.expandAll()
            self.file_tree.show()
        else:
            self.file_tree.hide()
            self.file_tree.clear_tree()

        file_path = str(path)
        widget.setText(file_path)
        self.file_loaded.emit(file_path)

    @Slot()
    def reset_page(self) -> None:
        self.input_entry.clear()
        self.input_entry.setPlaceholderText(self.DEF_INPUT_ENTRY_TXT)
        self.file_tree.hide()
        self.file_tree.clear_tree()
        self.worker = None
        self._loading_completed = False
