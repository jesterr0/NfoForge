from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QToolButton,
    QVBoxLayout,
)
from pymediainfo import MediaInfo

from src.backend.media_input import MediaInputBackEnd
from src.config.config import Config
from src.exceptions import MediaFileNotFoundError
from src.frontend.custom_widgets.dnd_factory import DNDLineEdit
from src.frontend.custom_widgets.file_tree import FileSystemTreeView
from src.frontend.global_signals import GSigs
from src.frontend.utils import QWidgetTempStyle, build_v_line
from src.frontend.utils.general_worker import GeneralWorker
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.packages.custom_types import ComparisonPair

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class MediaInput(BaseWizardPage):
    DEF_INPUT_ENTRY_TXT = "Open file or directory..."

    progress_signal = Signal(int, int, int)  # progress, completed files, total files

    # used in sandbox
    file_loaded = Signal(str)

    def __init__(
        self,
        config: Config,
        parent: "MainWindow | Any",
        on_finished_cb: Callable | None = None,
    ) -> None:
        super().__init__(config, parent)
        self.setObjectName("mediaInput")
        self.setTitle("Input")
        self.setCommitPage(True)

        self._on_finished_cb = on_finished_cb

        self.backend = MediaInputBackEnd(self.progress_signal)
        self.worker: GeneralWorker | None = None
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

        self.media_button = QToolButton(self)
        QTAThemeSwap().register(
            self.media_button, "ph.file-arrow-down-light", icon_size=QSize(24, 24)
        )
        self.media_button.clicked.connect(
            lambda: self.open_media_dialog(self.input_entry, "media", self.extensions)
        )

        self.media_dir_button = QToolButton(self)
        QTAThemeSwap().register(
            self.media_dir_button, "ph.folder-open-light", icon_size=QSize(24, 24)
        )
        self.media_dir_button.clicked.connect(
            lambda: self.open_dir_dialog(self.input_entry)
        )

        self.comparison_toggle_btn = QToolButton(self)
        self.comparison_toggle_btn.setCheckable(True)
        self.comparison_toggle_btn.setDisabled(True)
        self.comparison_toggle_btn.setToolTip("Toggle comparison mode")
        QTAThemeSwap().register(
            self.comparison_toggle_btn, "ph.link-light", icon_size=QSize(24, 24)
        )
        self.comparison_toggle_btn.toggled.connect(self._toggle_comparison_mode)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.input_entry, stretch=1)
        button_layout.addWidget(self.media_button)
        button_layout.addWidget(self.media_dir_button)
        button_layout.addWidget(build_v_line((0, 0, 0, 0)))
        button_layout.addWidget(self.comparison_toggle_btn)

        self.comparison_widget = QGroupBox(self)
        self.comparison_widget.hide()

        source_file_label = QLabel(
            '<span>To generate comparison images against a <span style="font-weight: bold;">source</span> '
            'file, open that file here then select its match in the <span style="font-weight: bold;">tree '
            "view</span> below.</span>",
            self.comparison_widget,
            wordWrap=True,
        )

        self.comparison_source_entry = DNDLineEdit(
            parent=self.comparison_widget,
            readOnly=True,
            placeholderText="Select source file to match...",
        )
        self.comparison_source_entry.set_extensions(("*",))
        self.comparison_source_entry.dropped.connect(self._dropped_comparison_source)

        self.comparison_browse_btn = QToolButton(self.comparison_widget)
        self.comparison_browse_btn.setToolTip("Browse source file")
        QTAThemeSwap().register(
            self.comparison_browse_btn,
            "ph.file-arrow-down-light",
            icon_size=QSize(24, 24),
        )
        self.comparison_browse_btn.clicked.connect(self._browse_comparison_source)

        source_input_layout = QHBoxLayout()
        source_input_layout.addWidget(self.comparison_source_entry, stretch=1)
        source_input_layout.addWidget(self.comparison_browse_btn)

        comparison_layout = QVBoxLayout(self.comparison_widget)
        comparison_layout.addWidget(source_file_label)
        comparison_layout.addLayout(source_input_layout)

        self.file_tree = FileSystemTreeView(parent=self)
        self.file_tree.hide()

        self.progress_bar = QProgressBar(self, minimum=0, maximum=100, textVisible=True)
        self.progress_bar.hide()

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addLayout(button_layout)
        self.main_layout.addWidget(self.comparison_widget)
        self.main_layout.addWidget(self.file_tree, stretch=1)
        self.main_layout.addWidget(
            self.progress_bar, alignment=Qt.AlignmentFlag.AlignBottom
        )
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
                QWidgetTempStyle().set_temp_style(
                    widget=entry, system_beep=True
                ).start()

        # validate comparison inputs if enabled
        if not self._validate_comparison_inputs():
            invalid_entries = True

        if invalid_entries:
            return False
        else:
            try:
                self.update_payload_data()
            except MediaFileNotFoundError as input_error:
                required_entries[0].setPlaceholderText(str(input_error))
            return False

    def _validate_comparison_inputs(self) -> bool:
        valid = True
        if self.comparison_toggle_btn.isChecked():
            # check if source file is provided
            if not self.comparison_source_entry.text().strip():
                valid = False
                self.comparison_source_entry.setPlaceholderText("Source file required")
                QWidgetTempStyle().set_temp_style(
                    widget=self.comparison_source_entry, system_beep=True
                ).start()

            # check if a file is selected in the tree
            if valid:
                selected_file = self._get_selected_comparison_file()
                if not selected_file:
                    valid = False
                    QMessageBox.warning(
                        self,
                        "Comparison Selection Required",
                        "Please select a file in the tree view to match with your source file.",
                    )

        return valid

    def update_payload_data(self) -> None:
        entry_data = Path(self.input_entry.text())
        self.config.media_input_payload.input_path = entry_data

        # handle single file
        if entry_data.is_file():
            self.config.media_input_payload.file_list = [entry_data]

        # handle directory
        elif entry_data.is_dir():
            checked_items: list[dict[str, Any]] = self.file_tree.get_checked_items()
            supported_files = sorted(
                [
                    Path(item["path"])
                    for item in checked_items
                    if not item.get("is_dir", False)
                    and Path(item["path"]).suffix.lower() in self.extensions
                ]
            )
            if not supported_files:
                raise MediaFileNotFoundError(
                    "No supported media files selected in directory "
                    f"({', '.join(self.config.cfg_payload.source_media_ext_filter)})"
                )

            self.config.media_input_payload.file_list = supported_files

        # store comparison match data if comparison mode is enabled
        comparison_pair = self.get_comparison_pair()
        if comparison_pair:
            self.config.media_input_payload.comparison_pair = comparison_pair

        self._run_worker()

    def _run_worker(self) -> None:
        input_path = self.config.media_input_payload.input_path
        file_list = self.config.media_input_payload.file_list
        comparison_pair = self.config.media_input_payload.comparison_pair

        if not input_path or not file_list:
            raise FileNotFoundError("Failed to detect input path or file list")

        self.set_working_dir(
            self.config.cfg_payload.working_dir / self.gen_unique_date_name(input_path)
        )

        # build copy of file_list to send to the worker, we don't want to modify the original
        # list of files that will be uploaded but we DO want mediainfo ran against these new files.
        files_to_process = file_list.copy()

        # add comparison files to the files_to_process list if not already included
        if comparison_pair:
            if comparison_pair.source not in files_to_process:
                files_to_process.append(comparison_pair.source)
            if comparison_pair.media not in files_to_process:
                files_to_process.append(comparison_pair.media)

        self.worker = GeneralWorker(
            func=self.backend.get_media_info_files, files=files_to_process, parent=self
        )
        self.worker.job_failed.connect(self._worker_failed)
        self.worker.job_finished.connect(self._worker_finished)
        GSigs().main_window_set_disabled.emit(True)
        GSigs().main_window_update_status_tip.emit(
            f"Parsing MediaInfo for {len(files_to_process)} files", 0
        )
        self.progress_signal.connect(self._handle_progress)
        self.worker.start()

    @Slot(object)
    def _worker_finished(self, files_mi_data: dict[Path, MediaInfo]) -> None:
        if not files_mi_data:
            raise AttributeError("Failed to detect MediaInfo")

        # store all MediaInfo data (main files + comparison files if any)
        self.config.media_input_payload.file_list_mediainfo = files_mi_data
        self._loading_completed = True
        GSigs().main_window_set_disabled.emit(False)
        GSigs().main_window_clear_status_tip.emit()
        self.progress_signal.disconnect(self._handle_progress)
        # if finished has a cb, utilize that instead of emit (for sandbox)
        if self._on_finished_cb:
            self._on_finished_cb()
        else:
            GSigs().wizard_next.emit()

    @Slot(str)
    def _worker_failed(self, msg: str) -> None:
        QMessageBox.critical(self, "Error", msg)
        self._loading_completed = False
        GSigs().main_window_set_disabled.emit(False)
        self.progress_signal.disconnect(self._handle_progress)

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
        self.comparison_toggle_btn.setDisabled(False)
        self.file_tree.build_tree(path)
        self.file_tree.expandAll()
        self.file_tree.show()
        file_path = str(path)
        widget.setText(file_path)
        self.file_loaded.emit(file_path)

    @Slot(int, int, int)
    def _handle_progress(self, progress: int, completed: int, total: int) -> None:
        # handle invalid progress values
        if progress is None or progress < 0:
            return

        if not self.progress_bar.isVisible():
            self.progress_bar.show()

        # show progress if greater than 0
        elif progress > 0:
            self.progress_bar.setValue(progress)
            self.progress_bar.setFormat(
                f"Parsed {completed} of {total} file(s) - {int(progress)}%"
            )

    @Slot(list)
    def _dropped_comparison_source(self, val: list[Path]) -> None:
        """Handle dropped file for comparison source."""
        if val:
            self.comparison_source_entry.setText(str(val[0]))

    @Slot()
    def _browse_comparison_source(self) -> None:
        """Browse for comparison source file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Source File", "", "All Files (*.*)"
        )
        if file_path:
            self.comparison_source_entry.setText(file_path)

    @Slot(bool)
    def _toggle_comparison_mode(self, enabled: bool) -> None:
        """Toggle comparison mode on/off."""
        if enabled:
            self.comparison_widget.show()
        else:
            self.comparison_widget.hide()
            self.comparison_source_entry.clear()

    def _get_selected_comparison_file(self) -> str | None:
        """Get the currently selected file from the tree for comparison."""
        if not self.file_tree.isVisible() or not self.comparison_widget.isVisible():
            return None

        selection_model = self.file_tree.selectionModel()
        if selection_model.hasSelection():
            selected_indexes = selection_model.selectedIndexes()
            if selected_indexes:
                # get the first column index (name column)
                index = selected_indexes[0]
                if index.column() != 0:
                    index = self.file_tree.model().index(index.row(), 0, index.parent())

                # get the item text from the model
                item_text = self.file_tree.model().data(
                    index, Qt.ItemDataRole.DisplayRole
                )
                if item_text and item_text in self.file_tree.items:
                    file_path = self.file_tree.items[item_text]
                    # only return if it's a file, not a directory
                    if Path(file_path).is_file():
                        return file_path

    def get_comparison_pair(self) -> ComparisonPair | None:
        """Get the comparison match as a tuple (source_file, selected_file)."""
        if not self.comparison_toggle_btn.isChecked():
            return None

        source_file = self.comparison_source_entry.text().strip()
        selected_file = self._get_selected_comparison_file()

        if source_file and selected_file:
            return ComparisonPair(source=Path(source_file), media=Path(selected_file))

    @Slot()
    def reset_page(self) -> None:
        self.input_entry.clear()
        self.input_entry.setPlaceholderText(self.DEF_INPUT_ENTRY_TXT)
        self.file_tree.hide()
        self.file_tree.clear_tree()
        self.progress_bar.reset()
        self.progress_bar.hide()
        self.worker = None
        self._loading_completed = False

        # reset comparison mode
        self.comparison_toggle_btn.setDisabled(True)
        self.comparison_toggle_btn.setChecked(False)
        self.comparison_widget.hide()
        self.comparison_source_entry.clear()
        self.comparison_source_entry.setPlaceholderText(
            "Select source file to match..."
        )
