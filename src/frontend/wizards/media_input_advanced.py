from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
)
from pymediainfo import MediaInfo

from src.backend.media_input import MediaInputBackEnd
from src.config.config import Config
from src.frontend.custom_widgets.dnd_factory import DNDLineEdit
from src.frontend.global_signals import GSigs
from src.frontend.utils.general_worker import GeneralWorker
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from src.frontend.wizards.wizard_base_page import BaseWizardPage

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class MediaInputAdvanced(BaseWizardPage):
    def __init__(self, config: Config, parent: "MainWindow") -> None:
        super().__init__(config, parent)

        self.setObjectName("mediaInputAdvanced")
        self.setTitle("Input - Advanced")
        self.setCommitPage(True)

        self.backend = MediaInputBackEnd()
        self.worker: GeneralWorker | None = None
        self._loading_completed = False

        self.source_label = QLabel("Source", self)
        self.source_entry = DNDLineEdit(self)
        self.source_entry.setReadOnly(True)
        self.source_entry.set_extensions(
            self.config.cfg_payload.source_media_ext_filter
        )
        self.source_entry.dropped.connect(
            lambda e: self._update_entries(e, self.source_entry)
        )
        self.source_button = QToolButton(self)
        QTAThemeSwap().register(
            self.source_button, "ph.file-arrow-down-light", icon_size=QSize(24, 24)
        )
        self.source_button.clicked.connect(
            lambda: self._open_filedialog(
                self.source_entry,
                "Source",
                self.config.cfg_payload.source_media_ext_filter,
            )
        )

        self.encode_label = QLabel("Encode", self)
        self.encode_entry = DNDLineEdit(self)
        self.encode_entry.setReadOnly(True)
        self.encode_entry.set_extensions(
            self.config.cfg_payload.encode_media_ext_filter
        )
        self.encode_entry.dropped.connect(
            lambda e: self._update_entries(e, self.encode_entry)
        )
        self.encode_button = QToolButton(self)
        QTAThemeSwap().register(
            self.encode_button, "ph.file-arrow-down-light", icon_size=QSize(24, 24)
        )
        self.encode_button.clicked.connect(
            lambda: self._open_filedialog(
                self.encode_entry,
                "Encode",
                self.config.cfg_payload.encode_media_ext_filter,
            )
        )

        layout = QVBoxLayout(self)
        layout.addLayout(
            self._button_form_layout(
                self.source_label, self.source_entry, self.source_button
            )
        )
        layout.addLayout(
            self._button_form_layout(
                self.encode_label, self.encode_entry, self.encode_button
            )
        )

    def validatePage(self) -> bool:
        if self._loading_completed:
            super().validatePage()
            return True

        required_entries = (
            self.source_entry,
            self.encode_entry,
        )
        invalid_entries = False

        for entry in required_entries:
            if entry.text().strip() == "" or entry.text() == entry.placeholderText():
                invalid_entries = True
                # TODO: Flash red or something once we theme it
                # entry.setStyleSheet("QLineEdit {border: 1px solid red; border-radius: 3px;}")
                entry.setPlaceholderText("Requires input")

        if not invalid_entries:
            self._update_payload_data()
        return False

    def _update_payload_data(self) -> None:
        self.config.media_input_payload.source_file = Path(self.source_entry.text())
        self.config.media_input_payload.encode_file = Path(self.encode_entry.text())
        self._parse_media_info()

    def _parse_media_info(self) -> None:
        files = (
            self.config.media_input_payload.source_file,
            self.config.media_input_payload.encode_file,
        )
        for file_path in files:
            if not file_path:
                raise FileNotFoundError("Failed to detect input path")
        self.set_working_dir(
            self.config.cfg_payload.working_dir
            / self.gen_unique_date_name(
                self.config.media_input_payload.encode_file  # pyright: ignore [reportArgumentType]
            )
        )
        self.worker = GeneralWorker(
            func=self.backend.get_media_info_files, files=files, parent=self
        )
        self.worker.job_failed.connect(self._worker_failed)
        self.worker.job_finished.connect(self._worker_finished)
        GSigs().main_window_set_disabled.emit(True)
        GSigs().main_window_update_status_tip.emit("Parsing MediaInfo", 0)
        self.worker.start()

    @Slot(list)
    def _worker_finished(self, mi_obj_list: list[MediaInfo]) -> None:
        if not mi_obj_list or (mi_obj_list and not isinstance(mi_obj_list, list)):
            raise AttributeError("Failed to detect MediaInfo")
        self.config.media_input_payload.source_file_mi_obj = mi_obj_list[0]
        self.config.media_input_payload.encode_file_mi_obj = mi_obj_list[1]
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
    def _open_filedialog(
        self, entry_widget: QLineEdit, title: str, extension: list
    ) -> None:
        supported_extensions = (
            f"{title} File ({' '.join(['*' + ext for ext in extension])})"
        )
        open_file, _ = QFileDialog.getOpenFileName(
            parent=self,
            caption=f"Open {title} File",
            filter=supported_extensions,
        )
        if open_file:
            entry_widget.setText(str(Path(open_file)))

    @Slot(list)
    def _update_entries(self, event: list, widget: QLineEdit) -> None:
        widget.setText(str(Path(event[0])))
        if self.source_entry.text() == self.encode_entry.text():
            widget.clear()
            widget.setPlaceholderText("Cannot open the same files...")

    @Slot()
    def reset_page(self) -> None:
        self.reset_entry(self.source_entry)
        self.reset_entry(self.encode_entry)
        self.worker = None
        self._loading_completed = False

    @staticmethod
    def reset_entry(entry: DNDLineEdit) -> None:
        entry.clear()
        entry.setPlaceholderText("")
