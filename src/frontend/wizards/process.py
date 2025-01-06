import re
import asyncio
import traceback
from typing import TYPE_CHECKING, Optional
from pathlib import Path

from pymediainfo import MediaInfo
from PySide6.QtCore import QObject, Slot, QThread, Signal
from PySide6.QtGui import QTextCursor, Qt
from PySide6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QMessageBox,
    QFileDialog,
    QProgressBar,
)

from src.config.config import Config
from src.backend.process import ProcessBackEnd
from src.enums.tracker_selection import TrackerSelection
from src.enums.upload_process import UploadProcessMode
from src.enums.media_mode import MediaMode
from src.enums.token_replacer import ColonReplace
from src.exceptions import ProcessError
from src.frontend.custom_widgets.basic_code_editor import CodeEditor, HighlightKeywords
from src.frontend.custom_widgets.sortable_qtreewidget import SortableQTreeWidget
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.payloads.tracker_search_result import TrackerSearchResult
from src.payloads.media_search import MediaSearchPayload
from src.nf_jinja2 import Jinja2TemplateEngine
from src.logger.nfo_forge_logger import LOG

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class BaseWorker(QThread):
    job_finished = Signal()
    job_failed = Signal(str, str)
    queued_text_update = Signal(str)
    queued_text_update_replace_last_line = Signal(str)
    caught_error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def _queued_text_update_cb(self, message: str) -> None:
        if message:
            self.queued_text_update.emit(message)

    def _queued_text_update_replace_last_line_cb(self, message: str) -> None:
        if message:
            self.queued_text_update_replace_last_line.emit(message)


class DupeWorker(BaseWorker):
    dupes_found = Signal(object)

    def __init__(
        self,
        backend: ProcessBackEnd,
        file_input: Path,
        processing_queue: dict[str, Path],
        media_search_payload: MediaSearchPayload,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.file_input = file_input
        self.processing_queue = processing_queue
        self.media_search_payload = media_search_payload

    def run(self) -> None:
        try:
            dupes = asyncio.run(
                self.backend.dupe_checks(
                    file_input=self.file_input,
                    process_dict=self.processing_queue,
                    queued_text_update=self._queued_text_update_cb,
                    media_search_payload=self.media_search_payload,
                )
            )
            self.dupes_found.emit(dupes)
        except Exception as e:
            self.job_failed.emit(str(e), traceback.format_exc())


class ProcessWorker(BaseWorker):
    queued_status_update = Signal(str, str)
    torrent_gen_progress = Signal(int)

    def __init__(
        self,
        backend: ProcessBackEnd,
        media_input: Path,
        jinja_engine: Jinja2TemplateEngine,
        source_file: Path | None,
        processing_queue: dict[str, Path],
        mediainfo_obj: MediaInfo,
        source_file_mi_obj: MediaInfo | None,
        media_mode: MediaMode,
        media_search_payload: MediaSearchPayload,
        colon_replacement: ColonReplace,
        releasers_name: str,
        screen_shots: str | None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.media_input = media_input
        self.jinja_engine = jinja_engine
        self.source_file = source_file
        self.processing_queue = processing_queue
        self.mediainfo_obj = mediainfo_obj
        self.source_file_mi_obj = source_file_mi_obj
        self.media_mode = media_mode
        self.media_search_payload = media_search_payload
        self.colon_replacement = colon_replacement
        self.releasers_name = releasers_name
        self.screen_shots = screen_shots

    def run(self) -> None:
        try:
            self.backend.process_trackers(
                media_input=self.media_input,
                jinja_engine=self.jinja_engine,
                source_file=self.source_file,
                process_dict=self.processing_queue,
                queued_status_update=self._queued_status_update_cb,
                queued_text_update=self._queued_text_update_cb,
                queued_text_update_replace_last_line=self._queued_text_update_replace_last_line_cb,
                torrent_gen_progress=self._torrent_gen_progress_cb,
                caught_error=self.caught_error,
                mediainfo_obj=self.mediainfo_obj,
                source_file_mi_obj=self.source_file_mi_obj,
                media_mode=self.media_mode,
                media_search_payload=self.media_search_payload,
                colon_replacement=self.colon_replacement,
                releasers_name=self.releasers_name,
                screen_shots=self.screen_shots,
            )
            self.job_finished.emit()
        except Exception as e:
            self.job_failed.emit(
                f"Failed to process trackers: {e}", traceback.format_exc()
            )

    def _queued_status_update_cb(self, tracker: str, status: str) -> None:
        if tracker and status:
            self.queued_status_update.emit(tracker, status)

    def _torrent_gen_progress_cb(self, progress: float) -> None:
        if progress:
            self.torrent_gen_progress.emit(progress)


class ProcessPage(BaseWizardPage):
    def __init__(self, config: Config, parent: "MainWindow") -> None:
        super().__init__(config, parent)
        self.setObjectName("processPage")
        self.setTitle("Process")

        self.config = config
        self.save_config = False
        self.backend = ProcessBackEnd(self.config)
        self.main_window = parent
        self.main_window.wizard_process_btn_clicked.connect(self.process_jobs)

        self.processing_mode = UploadProcessMode.DUPE_CHECK
        self.dupe_worker: DupeWorker | None = None
        self.process_worker: ProcessWorker | None = None

        self.tree_widget = SortableQTreeWidget(
            headers=("Tracker", "Status"), parent=self
        )
        self.tree_widget.items_re_arranged.connect(self._adjust_tracker_order)

        text_widget_label = QLabel("Log", self)
        self.text_widget = CodeEditor(
            line_numbers=False, wrap_text=True, mono_font=True, parent=self
        )
        self.text_widget.setReadOnly(True)
        self.apply_syntax_highlighting()

        self.progress_bar = QProgressBar(self)
        self.progress_bar.hide()

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.tree_widget, stretch=2)
        main_layout.addWidget(text_widget_label, alignment=Qt.AlignmentFlag.AlignBottom)
        main_layout.addWidget(self.text_widget, stretch=7)
        main_layout.addWidget(self.progress_bar, stretch=1)
        self.setLayout(main_layout)

    def apply_syntax_highlighting(self) -> None:
        highlight = [
            HighlightKeywords(
                re.compile(r"(Total potential dupes found.+)"), "#e1401d", True
            ),
            HighlightKeywords(re.compile(r"(?i)(fail.*)\b"), "#e1401d", False),
        ]
        for tracker in self.config.tracker_map.keys():
            tracker = re.escape(str(tracker))
            highlight.append(
                HighlightKeywords(re.compile(rf"'({tracker})':"), "#e1401d", True)
            )
        self.text_widget.highlight_keywords(highlight)

    @Slot()
    def process_jobs(self) -> None:
        # get paths and other things from the media input payload
        torrent_dir, detected_input, mediainfo_obj = self._handle_files()

        # get tracker paths and check for existing torrent files
        tracker_paths = self._handle_tracker_paths(torrent_dir, detected_input)
        if not tracker_paths:
            raise AttributeError("Could not determine tracker paths")

        self.main_window.set_disabled.emit(True)
        if self.processing_mode == UploadProcessMode.DUPE_CHECK:
            self.dupe_worker = DupeWorker(
                backend=self.backend,
                file_input=detected_input,
                processing_queue=tracker_paths,
                media_search_payload=self.config.media_search_payload,
            )
            self.dupe_worker.dupes_found.connect(self._on_dupes_found)
            self.dupe_worker.job_failed.connect(self._on_failed)
            self.dupe_worker.queued_text_update.connect(self._on_text_update)
            self.dupe_worker.queued_text_update_replace_last_line.connect(
                self._on_text_update_replace_last_line
            )
            self.dupe_worker.start()

        elif self.processing_mode == UploadProcessMode.UPLOAD:
            self.process_worker = ProcessWorker(
                backend=self.backend,
                media_input=detected_input,
                jinja_engine=self.config.jinja_engine,
                source_file=self.config.media_input_payload.source_file,
                processing_queue=tracker_paths,
                mediainfo_obj=mediainfo_obj,
                source_file_mi_obj=self.config.media_input_payload.source_file_mi_obj,
                media_mode=self.config.cfg_payload.media_mode,
                media_search_payload=self.config.media_search_payload,
                colon_replacement=self.config.cfg_payload.mvr_colon_replacement,
                releasers_name=self.config.cfg_payload.releasers_name,
                screen_shots=self.config.shared_data.url_data,
            )
            self.process_worker.caught_error.connect(self._log_caught_error)
            self.process_worker.job_finished.connect(self._on_finished)
            self.process_worker.queued_status_update.connect(self._on_status_update)
            self.process_worker.torrent_gen_progress.connect(
                self._on_torrent_gen_progress_update
            )
            self.process_worker.job_failed.connect(self._on_failed)
            self.process_worker.queued_text_update.connect(self._on_text_update)
            self.process_worker.queued_text_update_replace_last_line.connect(
                self._on_text_update_replace_last_line
            )
            self.process_worker.start()

    @Slot(object)
    def _on_dupes_found(
        self, dupes: dict[TrackerSelection, list[TrackerSearchResult]]
    ) -> None:
        if dupes:
            duplicate_base_str = "###### Potential Duplicates ######\n{}\n###### Potential Duplicates ######"
            duplicates = ""

            for tracker, releases in dupes.items():
                duplicates = duplicates + f"\n{tracker}:\n"
                for item in releases:
                    duplicates = duplicates + f"{item.name}\n"
            self._on_text_update(duplicate_base_str.format(duplicates.strip()))

        self.processing_mode = UploadProcessMode.UPLOAD
        self._job_ended()
        self.main_window.wizard_process_btn_change_txt.emit(
            "Process (Generate and Upload)"
        )

    @Slot()
    def _on_finished(self) -> None:
        self._job_ended()
        self.main_window.wizard_process_btn_set_hidden.emit()

    # TODO: will we reset everything or start over?
    @Slot(str, str)
    def _on_failed(self, e: str, trace_back: str) -> None:
        self._job_ended()
        self._on_text_update(f"\n{e}")
        LOG.error(LOG.LOG_SOURCE.FE, trace_back)

    def _job_ended(self) -> None:
        self.dupe_worker = None
        self.process_worker = None
        self.main_window.set_disabled.emit(False)

    @Slot(str, str)
    def _on_status_update(self, index: str, txt: str) -> None:
        """Used to update the `QLabel` associated with the tracker."""
        self.tree_widget.update_value(index, 1, txt)

    @Slot(str)
    def _on_text_update(self, txt: str) -> None:
        self.text_widget.appendPlainText(txt)
        self.text_widget.ensureCursorVisible()
        LOG.info(LOG.LOG_SOURCE.FE, txt)

    @Slot(str)
    def _on_text_update_replace_last_line(self, txt: str) -> None:
        cursor = self.text_widget.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(
            QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        cursor.removeSelectedText()
        cursor.insertText(txt)
        if not cursor.atEnd():
            cursor.deleteChar()
        self.text_widget.setTextCursor(cursor)

    @Slot(str)
    def _log_caught_error(self, txt: str) -> None:
        LOG.critical(LOG.LOG_SOURCE.BE, txt)

    @Slot(float)
    def _on_torrent_gen_progress_update(self, progress: float) -> None:
        if progress:
            if not self.progress_bar.isVisible():
                self.progress_bar.show()
            self.progress_bar.setValue(int(progress))
            if progress == 100:
                self.progress_bar.reset()
                self.progress_bar.hide()

    @Slot(list)
    def _adjust_tracker_order(self, data: list) -> None:
        if data:
            self.config.order_tracker_map(
                [TrackerSelection(t).value for (t, _) in data]
            )
            self.save_config = True

    def add_tracker_items(self) -> None:
        if self.config.shared_data.selected_trackers:
            self.tree_widget.add_rows(
                [
                    (str(item), "Queued")
                    for item in self.config.shared_data.selected_trackers
                ]
            )

    def get_inputs(self) -> tuple[Path, Optional[Path] | None, MediaInfo]:
        payload = self.config.media_input_payload
        media_in = payload.encode_file
        if not media_in:
            raise FileNotFoundError("Failed to detect encode input")
        renamed_out = payload.renamed_file
        media_info_obj = payload.encode_file_mi_obj
        if not media_info_obj:
            raise AttributeError("Failed to read media info for encode input")
        return (
            Path(media_in),
            Path(renamed_out) if renamed_out else None,
            media_info_obj,
        )

    def _handle_files(self) -> tuple[Path, Path, MediaInfo]:
        # get paths and other things from the media input payload
        og_input, renamed_input, mediainfo_obj = self.get_inputs()
        torrent_dir = (
            renamed_input.parent / f"{renamed_input.stem}_nf"
            if renamed_input
            else og_input.parent / f"{og_input.stem}_nf"
        )
        detected_input = renamed_input if renamed_input else og_input
        LOG.debug(LOG.LOG_SOURCE.FE, f"Detected file input: {detected_input}")

        # handle rename if we're uploading
        if self.processing_mode == UploadProcessMode.UPLOAD:
            # we're doing string comparison of inputs for case sensitive vs case insensitive systems
            if renamed_input and (str(og_input) != str(renamed_input)):
                self._on_text_update(
                    f"Renaming input file:\n'{og_input.name}' -> '{renamed_input.name}'\n"
                )
                try:
                    detected_input = self.backend.rename_file(
                        f_in=og_input, f_out=renamed_input
                    )

                    if not detected_input.exists():
                        detected_input_error = (
                            "Cannot continue, the detected input does not exist"
                        )
                        LOG.debug(LOG.LOG_SOURCE.FE, detected_input_error)
                        raise ProcessError(detected_input_error)
                except Exception as e:
                    LOG.error(
                        LOG.LOG_SOURCE.FE,
                        f"Failed to rename file: {e}\n{traceback.format_exc()}",
                    )
                    raise

        return torrent_dir, detected_input, mediainfo_obj

    def _handle_tracker_paths(
        self, torrent_dir: Path, detected_input: Path
    ) -> dict[str, Path] | None:
        tracker_paths = {}
        for tracker, _ in self.tree_widget.get_item_values():
            torrent_dir_out = torrent_dir / tracker.lower()
            torrent_dir_out.mkdir(parents=True, exist_ok=True)
            torrent_out = Path(torrent_dir_out / f"{detected_input.stem}.torrent")

            if self.processing_mode == UploadProcessMode.UPLOAD:
                if torrent_out.exists():
                    if (
                        QMessageBox.question(
                            self,
                            "Overwrite?",
                            f"\n\nTracker: {tracker}\n\nFile: {torrent_out}\n\nFile already "
                            "exists, would you like to overwrite?",
                        )
                        is QMessageBox.StandardButton.No
                    ):
                        new_torrent_out, _ = QFileDialog.getSaveFileName(
                            parent=self,
                            caption="Select Save Output",
                            filter="*.torrent",
                            dir=str(torrent_dir_out) if torrent_dir_out else "",
                        )
                        if not new_torrent_out:
                            return
                        torrent_out = Path(new_torrent_out)
            tracker_paths[tracker] = torrent_out

        if not tracker_paths:
            tracker_paths_error_msg = "Failed to generate trackers to upload to"
            LOG.error(LOG.LOG_SOURCE.FE, tracker_paths_error_msg)
            raise ProcessError(tracker_paths_error_msg)

        return tracker_paths

    def initializePage(self) -> None:
        self.add_tracker_items()

    @Slot()
    def reset_page(self) -> None:
        self.processing_mode = UploadProcessMode.DUPE_CHECK
        self.dupe_worker = None
        self.process_worker = None
        self.tree_widget.clear()
        self.text_widget.clear()
        self.progress_bar.reset()
