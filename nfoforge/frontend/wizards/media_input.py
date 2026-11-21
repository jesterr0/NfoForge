from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pymediainfo import MediaInfo
from PySide6.QtCore import QItemSelectionModel, QSize, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nfoforge.backend.media_input import MediaInputBackEnd
from nfoforge.backend.utils.media_files import filter_media_files
from nfoforge.backend.utils.working_dir import processing_dir
from nfoforge.config.config import ConfigManager
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.core.disc import (
    MISSING_BDINFO,
    MOUNTS,
    Disc,
    DiscError,
    DiscType,
    describe_disc,
    detect_disc,
    disc_size_class,
    disc_warnings,
    format_duration,
    is_disc_image,
    needs_playlist_choice,
    preferred_playlist,
)
from nfoforge.exceptions import MediaFileNotFoundError
from nfoforge.frontend.custom_widgets.dnd_factory import DNDLineEdit
from nfoforge.frontend.custom_widgets.file_tree import FileSystemTreeView
from nfoforge.frontend.global_signals import GSigs
from nfoforge.frontend.utils import QWidgetTempStyle, build_v_line
from nfoforge.frontend.utils.general_worker import GeneralWorker
from nfoforge.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from nfoforge.frontend.wizards.wizard_base_page import BaseWizardPage
from nfoforge.logger.nfo_forge_logger import LOG
from nfoforge.packages.custom_types import ComparisonPair


class MediaInput(BaseWizardPage):
    MEDIA_PLACEHOLDER_TXT = "Open file or directory..."
    SOURCE_PLACEHOLDER_TXT = "Select source file to match..."
    SCRIPT_PLACEHOLDER_TXT = "Optionally select script file..."

    progress_signal = Signal(int, int, int)  # progress, completed files, total files
    disc_progress_signal = Signal(float)  # BDInfo scan progress, 0 to 100

    # used in sandbox
    file_loaded = Signal(str)

    def __init__(
        self,
        config: ConfigManager,
        context: ProcessingContext,
        parent: QWidget,
        on_finished_cb: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(config, context, parent)
        self.setObjectName("mediaInput")
        self.setTitle("Input")
        self.setCommitPage(True)

        self._on_finished_cb = on_finished_cb

        self.backend = MediaInputBackEnd(self.progress_signal)
        self.worker: GeneralWorker | None = None
        self._loading_completed = False
        self._progress_connected = False
        # the disc the opened folder holds, when it is one
        self._disc: Disc | None = None

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

        # shown in place of the file tree for a full disc: the release is the
        # whole folder, and the only choice is which playlist describes it
        self.disc_widget = QGroupBox(self)
        self.disc_widget.hide()
        self.disc_note = QLabel(self.disc_widget, wordWrap=True)
        self.disc_table = QTableWidget(0, 4, self.disc_widget)
        self.disc_table.setHorizontalHeaderLabels(
            ("Playlist", "Duration", "Size", "Main")
        )
        self.disc_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.disc_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.disc_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.disc_table.verticalHeader().setVisible(False)
        self.disc_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        disc_layout = QVBoxLayout(self.disc_widget)
        disc_layout.addWidget(self.disc_note)
        disc_layout.addWidget(self.disc_table)

        self.progress_bar = QProgressBar(self, minimum=0, maximum=100, textVisible=True)
        self.progress_bar.hide()
        self.disc_progress_signal.connect(self._handle_disc_progress)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addLayout(button_layout)
        self.main_layout.addWidget(self.comparison_widget)
        self.main_layout.addWidget(self.file_tree, stretch=1)
        self.main_layout.addWidget(self.disc_widget, stretch=1)
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
        media_input = self.context.media_input
        media_input.input_path = entry_data
        media_input.discs.clear()
        selected_files: list[Path]

        # a full disc is one release, not the clips the tree happens to list
        if (entry_data.is_dir() or is_disc_image(entry_data)) and (
            disc := self._settled_disc()
        ):
            primary = disc.primary_media_file()
            if primary is None:
                raise MediaFileNotFoundError(f"No playable clip found on {disc.label}")
            selected_files = [primary]
            media_input.discs.append(disc)
            # an image is uploaded as the one file it is
            media_input.input_kind = "file" if disc.is_image else "directory"
            media_input.content_size = disc.size

        # handle single file
        elif entry_data.is_file():
            selected_files = [entry_data]

        # handle directory
        elif entry_data.is_dir():
            checked_items: list[dict[str, Any]] = self.file_tree.get_checked_items()
            # The tree is read-only, so `get_checked_items` reports *everything*
            # it walked, recursively and unfiltered. `file_list` is the release's
            # episode set -- it is what MediaInfo parses, what the series episode
            # mapper asks the user to map, and what `{episode_mediainfo}` renders
            # -- so subtitles, .nfo files and sample clips have to be dropped here
            # rather than travelling the whole pipeline as if they were episodes.
            # They are not abandoned: the rename step names them after the episode
            # they belong to (see `find_sidecars`).
            selected_files = sorted(
                filter_media_files(
                    Path(item["path"])
                    for item in checked_items
                    if not item.get("is_dir", False)
                )
            )
            if not selected_files:
                raise MediaFileNotFoundError(
                    "No supported video files found in directory"
                )
        else:
            raise MediaFileNotFoundError(f"Input does not exist: {entry_data}")

        # store comparison match data if comparison mode is enabled
        self.context.media_input.file_list[:] = selected_files
        self.context.media_input.comparison_pair = self.get_comparison_pair()

        self._run_worker()

    def _settled_disc(self) -> Disc | None:
        """The opened disc with the picked playlist selected, or None if not a disc."""
        disc = self._disc
        if disc is None:
            return None
        row = self.disc_table.currentRow()
        item = self.disc_table.item(row, 0) if row >= 0 else None
        try:
            if item is None:
                raise DiscError(f"Select a playlist on {disc.label}")
            disc.select(item.text())
            if disc.disc_type is DiscType.BDMV and not (
                self.config.settings.dependencies.bdinfo
            ):
                raise DiscError(MISSING_BDINFO)
        except DiscError as error:
            QMessageBox.warning(self, "Disc Input", str(error))
            raise MediaFileNotFoundError(str(error).splitlines()[0]) from error
        return disc

    def _show_disc(self, disc: Disc) -> None:
        """Offer the disc's playlists, the likely main feature pre-selected."""
        kind = "Blu-ray" if disc.disc_type is DiscType.BDMV else "DVD"
        self.disc_widget.setTitle(
            f"{kind} {'image' if disc.is_image else 'disc'}: {disc.label} "
            f"({disc_size_class(disc.disc_type, disc.size)}, "
            f"{disc.size / 1024**3:.2f} GiB)"
        )
        unit = "playlist" if disc.disc_type is DiscType.BDMV else "title set"
        note = f"The whole disc is uploaded. Pick the {unit} that is the main feature."
        if needs_playlist_choice(disc):
            note += (
                f" This disc has {len(disc.main_playlists())} possible main "
                f"{unit}s: check that the right one is selected."
            )
        for warning in disc_warnings(disc):
            note += f"\nWarning: {warning}"
        self.disc_note.setText(note)

        # like-sized title sets on a DVD are episodes: the first stands for them
        mains = disc.main_playlists()
        preferred = (
            mains[0] if mains and disc.disc_type is DiscType.DVD else None
        ) or preferred_playlist(disc)
        self.disc_table.clearSelection()
        self.disc_table.setRowCount(len(disc.playlists))
        for row, playlist in enumerate(disc.playlists):
            for column, text in enumerate(
                (
                    playlist.playlist_id,
                    format_duration(playlist.duration),
                    f"{playlist.size / 1024**3:.2f} GiB",
                    "Yes" if playlist.is_main else "",
                )
            ):
                self.disc_table.setItem(row, column, QTableWidgetItem(text))
            if playlist is preferred:
                self.disc_table.selectRow(row)
        self.disc_widget.show()

    def _load_input(
        self, files: list[Path], disc: Disc | None, report_dir: Path
    ) -> tuple[dict[Path, MediaInfo], dict[Path, str], str | None]:
        """Worker job: MediaInfo for `files`, then the disc reports.

        Returns the MediaInfo, the files it could not read, and the reason the
        disc could not be described, if it could not.
        """
        parsed, failures = self.backend.get_media_info_files(files=files)
        if disc is None or failures:
            return parsed, failures, None
        try:
            describe_disc(
                disc,
                self.config.settings.dependencies.bdinfo,
                report_dir,
                self.disc_progress_signal.emit,
            )
        except DiscError as error:
            return parsed, failures, str(error)
        return parsed, failures, None

    def _run_worker(self) -> None:
        input_path = self.context.media_input.input_path
        file_list = self.context.media_input.file_list
        comparison_pair = self.context.media_input.comparison_pair

        if not input_path or not file_list:
            raise FileNotFoundError("Failed to detect input path or file list")

        self.set_working_dir(
            processing_dir(self.config.settings.general.working_dir)
            / self.gen_unique_date_name(input_path)
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

        discs = self.context.media_input.discs
        self.worker = GeneralWorker(
            func=self._load_input,
            parent=self,
            files=files_to_process,
            disc=discs[0] if discs else None,
            report_dir=self.context.media_input.require_working_dir() / "bdinfo",
        )
        self.worker.job_failed.connect(self._worker_failed)
        self.worker.job_finished.connect(self._worker_finished)
        GSigs().main_window_set_disabled.emit(True)
        GSigs().main_window_update_status_tip.emit(
            f"Parsing MediaInfo for {len(files_to_process)} files", 0
        )
        if not self._progress_connected:
            self.progress_signal.connect(self._handle_progress)
            self._progress_connected = True
        self.worker.start()

    @Slot(object)
    def _worker_finished(
        self, result: tuple[dict[Path, MediaInfo], dict[Path, str], str | None]
    ) -> None:
        files_mi_data, failures, disc_error = result
        if disc_error:
            self._handle_worker_failure(disc_error, "Disc Error")
            return

        if failures:
            failure_display = "\n".join(
                f"- {path}: {reason}" for path, reason in sorted(failures.items())
            )
            self._handle_worker_failure(
                "MediaInfo could not be read for the following file(s):\n"
                f"{failure_display}"
            )
            return

        if not files_mi_data:
            self._handle_worker_failure(
                "Failed to detect MediaInfo for the selected files."
            )
            return

        # store all MediaInfo data (main files + comparison files if any)
        self.context.media_input.file_list_mediainfo.update(files_mi_data)
        self._loading_completed = True
        GSigs().main_window_set_disabled.emit(False)
        GSigs().main_window_clear_status_tip.emit()
        self._disconnect_progress_signal()
        # if finished has a cb, utilize that instead of emit (for sandbox)
        if self._on_finished_cb:
            self._on_finished_cb()
        else:
            GSigs().wizard_next.emit()

    @Slot(str)
    def _worker_failed(self, msg: str) -> None:
        self._handle_worker_failure(msg)

    def _handle_worker_failure(
        self, message: str, title: str = "MediaInfo Error"
    ) -> None:
        """Restore the page after the input worker failed."""

        self._loading_completed = False
        self._disconnect_progress_signal()
        GSigs().main_window_set_disabled.emit(False)
        GSigs().main_window_clear_status_tip.emit()
        QMessageBox.critical(self, title, message)

    def _disconnect_progress_signal(self) -> None:
        if not self._progress_connected:
            return
        try:
            self.progress_signal.disconnect(self._handle_progress)
        except (RuntimeError, TypeError):
            # The signal may already have been disconnected during teardown.
            pass
        self._progress_connected = False

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

    def _update_media_input(self, data: Sequence[Path] | Path) -> None:
        # uncheck/clear comparison section on new files opened
        self.comparison_toggle_btn.setChecked(False)
        self._toggle_comparison_mode(False)
        self._loading_completed = False

        if not data:
            return

        # update entry data
        path = Path(data[0]) if isinstance(data, Sequence) else data
        if self._disc is not None and self._disc.image is not None:
            # opened but never used: no release holds it for the reset below
            MOUNTS.release(self._disc.image)
        self._disc = None
        self.disc_widget.hide()
        # before detection: a reset unmounts the previous release's image,
        # which may be this same one
        self.context.media_input.reset(path)
        try:
            disc = detect_disc(path) if path.is_dir() or is_disc_image(path) else None
        except DiscError as error:
            # disc-shaped but unusable: never fall back to its loose clips
            QMessageBox.warning(self, "Disc Input", str(error))
            self.context.media_input.reset()
            self.media_input_entry.clear()
            self.file_tree.hide()
            self.comparison_toggle_btn.setDisabled(True)
            return

        if disc is not None:
            self._disc = disc
            self.file_tree.hide()
            # comparison images need a source to match; a disc is the source
            self.comparison_toggle_btn.setDisabled(True)
            self._show_disc(disc)
        else:
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

    @Slot(float)
    def _handle_disc_progress(self, percent: float) -> None:
        if not self.progress_bar.isVisible():
            self.progress_bar.show()
        self.progress_bar.setValue(int(percent))
        self.progress_bar.setFormat(f"Scanning disc with BDInfo - {int(percent)}%")

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
        return None

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
        return None

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
        return None

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
            # scrollTo's own failures are covered by the outer catch below;
            # a separate inner try/except here would handle them identically
            self.file_tree.scrollTo(idx)
        except Exception as error:
            # best effort only; prevent breaking the flow on unexpected shapes
            LOG.debug(
                LOG.LOG_SOURCE.FE,
                f"Could not auto-select the single tree file: {error}",
            )

    def _reset_comparison_widget(self, set_disabled: bool) -> None:
        """Hides comparison section and resets all entries"""
        self.comparison_toggle_btn.setDisabled(set_disabled)
        self.comparison_toggle_btn.setChecked(False)
        self.comparison_source_entry.clear()
        self.comparison_source_entry.setPlaceholderText(self.SOURCE_PLACEHOLDER_TXT)
        self.script_entry.clear()
        self.script_entry.setPlaceholderText(self.SCRIPT_PLACEHOLDER_TXT)
        self.comparison_widget.hide()
