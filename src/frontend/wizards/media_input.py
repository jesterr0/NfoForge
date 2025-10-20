from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pymediainfo import MediaInfo
from PySide6.QtCore import QItemSelectionModel, QSize, Qt, Signal, Slot
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
    MEDIA_PLACEHOLDER_TXT = "Open file or directory..."
    SOURCE_PLACEHOLDER_TXT = "Select source file to match..."
    SCRIPT_PLACEHOLDER_TXT = "Optionally select script file..."

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

        self.media_input_entry: QLineEdit = DNDLineEdit(
            parent=self, readOnly=True, placeholderText=self.MEDIA_PLACEHOLDER_TXT
        )
        self.media_input_entry.set_extensions(("*",))
        self.media_input_entry.set_accept_dir(True)
        self.media_input_entry.dropped.connect(self._update_media_input)

        self.media_button = QToolButton(self)
        QTAThemeSwap().register(
            self.media_button, "ph.file-arrow-down-light", icon_size=QSize(24, 24)
        )
        self.media_button.clicked.connect(self.open_media_input_dialog)

        self.media_dir_button = QToolButton(self)
        QTAThemeSwap().register(
            self.media_dir_button, "ph.folder-open-light", icon_size=QSize(24, 24)
        )
        self.media_dir_button.clicked.connect(self.open_media_input_dir_dialog)

        self.comparison_toggle_btn = QToolButton(self)
        self.comparison_toggle_btn.setCheckable(True)
        self.comparison_toggle_btn.setDisabled(True)
        self.comparison_toggle_btn.setToolTip("Toggle comparison mode")
        QTAThemeSwap().register(
            self.comparison_toggle_btn, "ph.link-light", icon_size=QSize(24, 24)
        )
        self.comparison_toggle_btn.toggled.connect(self._toggle_comparison_mode)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.media_input_entry, stretch=1)
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
            placeholderText=self.SOURCE_PLACEHOLDER_TXT,
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

        script_label = QLabel(
            '<span>You can <span style="font-weight: bold;">optionally</span> supply a script '
            "<i>(.vpy, .avs)</i>. It will be used to read crop information and apply those crops "
            "in comparison image workflows</span>",
            self.comparison_widget,
            wordWrap=True,
        )

        self.script_entry = DNDLineEdit(
            parent=self.comparison_widget,
            readOnly=True,
            placeholderText=self.SCRIPT_PLACEHOLDER_TXT,
        )
        self.script_entry.set_extensions((".vpy", ".avs", ".txt"))
        self.script_entry.dropped.connect(self._dropped_script)

        self.browse_script_btn = QToolButton(self.comparison_widget)
        self.browse_script_btn.setToolTip("Browse script file")
        QTAThemeSwap().register(
            self.browse_script_btn,
            "ph.file-arrow-down-light",
            icon_size=QSize(24, 24),
        )
        self.browse_script_btn.clicked.connect(self._browse_script)

        script_layout = QHBoxLayout()
        script_layout.addWidget(self.script_entry, stretch=1)
        script_layout.addWidget(self.browse_script_btn)

        comparison_layout = QVBoxLayout(self.comparison_widget)
        comparison_layout.addWidget(source_file_label)
        comparison_layout.addLayout(source_input_layout)
        comparison_layout.addWidget(script_label)
        comparison_layout.addLayout(script_layout)

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
            self.media_input_entry,
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
        entry_data = Path(self.media_input_entry.text())
        self.config.media_input_payload.input_path = entry_data

        # handle single file
        if entry_data.is_file():
            self.config.media_input_payload.file_list.append(entry_data)

        # handle directory
        elif entry_data.is_dir():
            checked_items: list[dict[str, Any]] = self.file_tree.get_checked_items()
            supported_files = sorted(
                [
                    Path(item["path"])
                    for item in checked_items
                    if not item.get("is_dir", False)
                ]
            )
            if not supported_files:
                raise MediaFileNotFoundError(
                    "No supported media files selected in directory"
                )

            self.config.media_input_payload.file_list.extend(supported_files)

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
        self.config.media_input_payload.file_list_mediainfo.update(files_mi_data)
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
    def open_media_input_dialog(self) -> None:
        open_file, _ = QFileDialog.getOpenFileName(
            parent=self,
            caption="Open Media File",
            filter="Media Files (*.*)",
        )
        if open_file:
            self._update_media_input(Path(open_file))

    @Slot()
    def open_media_input_dir_dialog(self) -> None:
        open_dir = QFileDialog.getExistingDirectory(
            parent=self,
            caption="Select Directory",
        )
        if open_dir:
            self._update_media_input(Path(open_dir))

    def _update_media_input(self, data: Sequence | Path) -> None:
        # uncheck/clear comparison section on new files opened
        self.comparison_toggle_btn.setChecked(False)
        self._toggle_comparison_mode(False)

        if not data:
            return

        # update entry data
        path = Path(data[0]) if isinstance(data, Sequence) else data
        self.comparison_toggle_btn.setDisabled(False)
        self.file_tree.build_tree(path)
        self.file_tree.expandAll()
        self.file_tree.show()
        file_path = str(path)
        self.media_input_entry.setText(file_path)
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
            self._auto_select_single_comp_tree_file()

    @Slot()
    def _browse_comparison_source(self) -> None:
        """Browse for comparison source file."""
        path, _ = QFileDialog.getOpenFileName(
            parent=self,
            caption="Select Source File",
            dir=self._get_dialog_dir_path() or "",
            filter="Media Files (*.*)",
        )
        if path:
            self.comparison_source_entry.setText(path)
            self._auto_select_single_comp_tree_file()

    @Slot(list)
    def _dropped_script(self, val: list[Path]) -> None:
        """Handle dropped file for script."""
        if val:
            self.script_entry.setText(str(val[0]))

    @Slot()
    def _browse_script(self) -> None:
        """Browse for comparison script file."""
        path, _ = QFileDialog.getOpenFileName(
            parent=self,
            caption="Select Script File",
            dir=self._get_dialog_dir_path() or "",
            filter="Script (*.vpy *.avs *.txt)",
        )
        if path:
            self.script_entry.setText(path)

    def _get_dialog_dir_path(self) -> str | None:
        """Return string path directory."""
        path = (
            Path(self.media_input_entry.text())
            if self.media_input_entry.text()
            else None
        )
        if path and path.is_dir():
            return str(path)
        elif path and path.is_file():
            return str(path.parent)

    @Slot(bool)
    def _toggle_comparison_mode(self, enabled: bool) -> None:
        """Toggle comparison mode on/off."""
        if enabled:
            self.comparison_widget.show()
        else:
            self._reset_comparison_widget(False)

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

        source_file = self.comparison_source_entry.text()
        selected_file = self._get_selected_comparison_file()
        script_file = self.script_entry.text()

        if source_file and selected_file:
            return ComparisonPair(
                source=Path(source_file),
                media=Path(selected_file),
                script=Path(script_file) if script_file else None,
            )

    def _auto_select_single_comp_tree_file(self) -> None:
        """
        If the tree has exactly one file, select it.
        Uses cached metadata from tree building to avoid filesystem stats.
        """
        try:
            # collect at most two file candidates and short-circuit if > 1
            candidates: list[str] = []
            for p in self.file_tree.items.values():
                # use cached metadata to avoid filesystem stat
                meta = getattr(self.file_tree, "item_meta", {}).get(str(p), {})
                is_dir = meta.get("is_dir")

                # determine if it's a file using metadata or fallback
                if is_dir is False:
                    candidates.append(p)
                # metadata missing, fallback to filesystem
                elif is_dir is None:
                    if Path(p).is_file():
                        candidates.append(p)
                # if is_dir is True, skip (it's a directory)

                if len(candidates) > 1:
                    return

            if len(candidates) != 1:
                return

            target = candidates[0]

            # best-effort: find display key and select in model
            item_text = next(
                k
                for k, v in self.file_tree.items.items()
                if v == target or str(v) == str(target)
            )
            model = self.file_tree.model()
            matches = model.match(
                model.index(0, 0),
                Qt.ItemDataRole.DisplayRole,
                item_text,
                hits=1,
                flags=Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive,
            )
            if not matches:
                return
            idx = matches[0]
            sel_model = self.file_tree.selectionModel()
            sel_model.select(
                idx,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
            try:
                self.file_tree.scrollTo(idx)
            except Exception:
                pass
        except Exception:
            # best effort only; prevent breaking the flow on unexpected shapes
            pass

    def _reset_comparison_widget(self, set_disabled: bool) -> None:
        """Hides comparison section and resets all entries"""
        self.comparison_toggle_btn.setDisabled(set_disabled)
        self.comparison_toggle_btn.setChecked(False)
        self.comparison_source_entry.clear()
        self.comparison_source_entry.setPlaceholderText(self.SOURCE_PLACEHOLDER_TXT)
        self.script_entry.clear()
        self.script_entry.setPlaceholderText(self.SCRIPT_PLACEHOLDER_TXT)
        self.comparison_widget.hide()

    @Slot()
    def reset_page(self) -> None:
        self.media_input_entry.clear()
        self.media_input_entry.setPlaceholderText(self.MEDIA_PLACEHOLDER_TXT)
        self.file_tree.hide()
        self.file_tree.clear_tree()
        self.progress_bar.reset()
        self.progress_bar.hide()
        self.worker = None
        self._loading_completed = False
        self._reset_comparison_widget(True)
