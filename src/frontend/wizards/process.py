import asyncio
import traceback
from copy import deepcopy
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from pymediainfo import MediaInfo
from PySide6.QtCore import QEventLoop, QObject, QThread, Signal, Slot
from PySide6.QtGui import Qt, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from src.backend.process import ProcessBackEnd
from src.backend.utils.file_utilities import open_explorer
from src.config.config import Config
from src.enums.image_host import ImageHost, ImageSource
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.upload_process import UploadProcessMode
from src.exceptions import ProcessError
from src.frontend.custom_widgets.combo_qtree import ComboBoxTreeWidget
from src.frontend.custom_widgets.overview_dialog import OverviewDialog
from src.frontend.custom_widgets.prompt_token_editor_dialog import (
    PromptTokenEditorDialog,
)
from src.frontend.global_signals import GSigs
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.logger.nfo_forge_logger import LOG
from src.nf_jinja2 import Jinja2TemplateEngine
from src.packages.custom_types import ImageUploadFromTo
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.payloads.tracker_search_result import TrackerSearchResult

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
    results = Signal(object)

    def __init__(
        self,
        backend: ProcessBackEnd,
        processing_queue: list[TrackerSelection],
        media_input_payload: MediaInputPayload,
        media_search_payload: MediaSearchPayload,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.media_input_payload = media_input_payload
        self.processing_queue = processing_queue
        self.media_search_payload = media_search_payload

    def run(self) -> None:
        async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(async_loop)
        try:
            dupes = async_loop.run_until_complete(
                self.backend.dupe_checks(
                    processing_queue=self.processing_queue,
                    media_input_payload=self.media_input_payload,
                    media_search_payload=self.media_search_payload,
                )
            )
            self.results.emit(dupes)
        except Exception as e:
            self.job_failed.emit(str(e), traceback.format_exc())
        finally:
            async_loop.close()


class ProcessWorker(BaseWorker):
    queued_status_update = Signal(str, str)
    progress_signal = Signal(int)
    prompt_tokens_signal = Signal(list)
    overview_signal = Signal(object)

    def __init__(
        self,
        backend: ProcessBackEnd,
        tracker_data: dict[str, Any],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.tracker_data = tracker_data

        self._prompt_tokens_response = None
        self._overview_prompt = None

    def run(self) -> None:
        try:
            self.backend.process_trackers(
                process_dict=self.tracker_data,
                queued_status_update=self._queued_status_update_cb,
                queued_text_update=self._queued_text_update_cb,
                queued_text_update_replace_last_line=self._queued_text_update_replace_last_line_cb,
                progress_bar_cb=self._progress_cb,
                caught_error=self.caught_error,
                token_prompt_cb=self.token_prompt_and_wait_cb,
                overview_cb=self.overview_prompt_and_wait_cb,
            )
            self.job_finished.emit()
        except Exception as e:
            self.job_failed.emit(
                f"Failed to process trackers: {e}", traceback.format_exc()
            )

    def _queued_status_update_cb(self, tracker: str, status: str) -> None:
        if tracker and status:
            self.queued_status_update.emit(tracker, status)

    def _progress_cb(self, progress: float) -> None:
        if progress:
            self.progress_signal.emit(progress)

    def token_prompt_and_wait_cb(
        self, tokens: Sequence[str] | None
    ) -> dict[str, str] | None:
        if not tokens:
            return

        self._prompt_tokens_response = None
        self.prompt_tokens_signal.emit(tokens)
        # start event loop
        loop = QEventLoop()

        @Slot(object)
        def on_response(
            response: dict[TrackerSelection, dict[str | None, str]] | None,
        ) -> None:
            self._prompt_tokens_response = response
            loop.quit()

        # wait for response
        GSigs().prompt_tokens_response.connect(on_response)
        loop.exec_()
        GSigs().prompt_tokens_response.disconnect(on_response)

        # return response
        return self._prompt_tokens_response

    def overview_prompt_and_wait_cb(
        self, data: dict[TrackerSelection, dict[str | None, str]] | None
    ) -> dict[TrackerSelection, dict[str | None, str]] | None:
        if not data:
            return

        self._overview_prompt = None
        self.overview_signal.emit(data)

        # start loop
        loop = QEventLoop()

        @Slot(object)
        def on_response(
            response: dict[TrackerSelection, dict[str | None, str]] | None,
        ) -> None:
            self._overview_prompt = response
            loop.quit()

        # wait for response
        GSigs().overview_prompt_response.connect(on_response)
        loop.exec_()
        GSigs().overview_prompt_response.disconnect(on_response)

        # return response
        return self._overview_prompt


class ProcessPage(BaseWizardPage):
    THEMES = {
        "dark": {"box_color": "#626262"},
        "light": {"box_color": "#e6e6e6"},
    }

    def __init__(self, config: Config, parent: "MainWindow") -> None:
        super().__init__(config, parent)
        self.setObjectName("processPage")
        self.setTitle("Process")

        self.config = config
        self.save_config = False
        self.backend = ProcessBackEnd(self.config)
        self.main_window = parent
        GSigs().wizard_process_btn_clicked.connect(self.process_jobs)

        self.processing_mode = UploadProcessMode.DUPE_CHECK
        self.dupe_worker: DupeWorker | None = None
        self.process_worker: ProcessWorker | None = None

        self.tracker_process_tree = ComboBoxTreeWidget(
            headers=("Tracker", "Image Host", "Status"), parent=self
        )
        self.tracker_process_tree.setSelectionMode(
            self.tracker_process_tree.SelectionMode.NoSelection
        )
        self.tracker_process_tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tracker_process_tree.combo_changed.connect(self._tree_combo_changed)

        text_widget_label = QLabel("Log", self)

        self.text_widget = QTextBrowser(parent=self, openExternalLinks=True)

        self._progress_bar_def_range = (0, 10000)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(*self._progress_bar_def_range)
        self.progress_bar.hide()

        self.open_temp_output_btn = QPushButton("Open Working Directory", self)
        self.open_temp_output_btn.setToolTip(
            "Opens current working directory in operating systems explorer"
        )
        self.open_temp_output_btn.clicked.connect(self._open_temp_output)
        self.open_temp_output_btn.hide()

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.tracker_process_tree, stretch=3)
        main_layout.addWidget(text_widget_label, alignment=Qt.AlignmentFlag.AlignBottom)
        main_layout.addWidget(self.text_widget, stretch=5)
        main_layout.addWidget(self.progress_bar, stretch=1)
        main_layout.addWidget(
            self.open_temp_output_btn, alignment=Qt.AlignmentFlag.AlignRight
        )
        self.setLayout(main_layout)

    @Slot()
    def process_jobs(self) -> None:
        # get paths and other things from the media input payload
        detected_input = self._handle_files()

        # get tracker data and check for existing torrent files
        tracker_data = self._gather_tracker_data(detected_input)
        if not tracker_data:
            raise AttributeError("Could not determine tracker data")

        GSigs().wizard_set_disabled.emit(True)
        self.tracker_process_tree.setDisabled(True)

        if self.processing_mode is UploadProcessMode.DUPE_CHECK:
            self.dupe_worker = DupeWorker(
                backend=self.backend,
                processing_queue=[TrackerSelection(x) for x in tracker_data.keys()],
                media_input_payload=self.config.media_input_payload,
                media_search_payload=self.config.media_search_payload,
                parent=self,
            )
            self.dupe_worker.results.connect(self._on_dupe_results)
            self.dupe_worker.job_failed.connect(self._on_dupes_failed)
            self._on_text_update(
                '<h3 style="margin: 0; padding: 0;">📋 Checking for dupes:</h3>',
            )
            self.dupe_worker.start()

        elif self.processing_mode is UploadProcessMode.UPLOAD:
            if self.save_config:
                self.save_config = False
                self._update_last_used_host()

            if not self.config.media_search_payload.media_type:
                raise AttributeError("Failed to determine MediaType")

            self.process_worker = ProcessWorker(
                backend=self.backend,
                tracker_data=tracker_data,
                parent=self,
            )
            self.process_worker.caught_error.connect(self._log_caught_error)
            self.process_worker.job_finished.connect(self._on_finished)
            self.process_worker.queued_status_update.connect(self._on_status_update)
            self.process_worker.progress_signal.connect(self._on_progress_update)
            self.process_worker.job_failed.connect(self._on_failed)
            self.process_worker.queued_text_update.connect(self._on_text_update)
            self.process_worker.queued_text_update_replace_last_line.connect(
                self._on_text_update_replace_last_line
            )
            self.process_worker.prompt_tokens_signal.connect(
                self._on_prompt_tokens_signal
            )
            self.process_worker.overview_signal.connect(self._on_overview_signal)
            self.process_worker.start()

    @Slot(object)
    def _on_dupe_results(
        self,
        dupes: dict[
            TrackerSelection,
            tuple[TrackerSelection, bool, list[TrackerSearchResult] | str],
        ],
    ) -> None:
        if dupes:
            total_dupes = 0
            duplicates = ""
            for tracker, result in dupes.items():
                _, success, data = result
                if success:
                    if isinstance(data, list) and data:
                        total_dupes += len(data)
                        duplicates += (
                            "<div style='border: 1px solid #d4d4d4; border-radius: 6px; "
                            "margin: 10px 0 16px 0; padding: 8px 10px;'>"
                            f"<b style='font-size: 1.08em;'>{tracker}</b>"
                            "<table style='border-collapse:collapse; margin-top:6px;'>"
                        )
                        for item in data:
                            duplicates += (
                                "<tr>"
                                "<td style='padding: 10px 4px; border-bottom: 1px solid #eee;'>"
                                f'📄 <a href="{item.url}" rel="noreferrer nofollow" style="color: #1976d2; '
                                f'text-decoration: underline; font-weight: bold;">{item.name}</a>'
                                "</td>"
                                "</tr>"
                            )
                        duplicates += "</table></div>"
                else:
                    # error string
                    duplicates += (
                        f"<div style='border: 1px solid #d4d4d4; border-radius: 6px; "
                        "margin: 10px 0 16px 0; padding: 8px 10px;'>"
                        f"<b style='font-size: 1.08em;'>{tracker}</b>"
                        f"<br /><span style='color: red;'>Error: {data}</span>"
                        "</div>"
                    )
            if total_dupes == 0 and not duplicates:
                self._on_text_update("<br /><span>✅ No duplicates found</span>")
            else:
                self._on_text_update(
                    f"<br /><span>⚠️ Total potential dupes found: {total_dupes}</span>"
                    + duplicates
                )
        else:
            self._on_text_update("<br /><span>✅ No duplicates found</span>")

        self.processing_mode = UploadProcessMode.UPLOAD
        self._job_ended()
        GSigs().wizard_process_btn_change_txt.emit("Process (Generate and Upload)")

    @Slot(str, str)
    def _on_dupes_failed(self, e: str, trace_back: str) -> None:
        self._on_failed(e, trace_back)
        # set process mode to upload if user wants to continue anyways
        if (
            QMessageBox.question(
                self,
                "Continue",
                "Failed to detect dupes (see logs), would you like to continue uploading? Select"
                " 'No' if you'd like to attempt to check for dupes again"
                "\n\nNote: You should still check if duplicates for your release exists.",
            )
            is QMessageBox.StandardButton.Yes
        ):
            self.processing_mode = UploadProcessMode.UPLOAD

    @Slot()
    def _on_finished(self) -> None:
        self._job_ended()
        GSigs().wizard_process_btn_set_hidden.emit()

    @Slot(str, str)
    def _on_failed(self, e: str, trace_back: str) -> None:
        self._job_ended()
        self._on_text_update(f"<br /><p>{e}</p>")
        LOG.error(LOG.LOG_SOURCE.FE, trace_back)

    def _job_ended(self) -> None:
        self.dupe_worker = None
        # if we just finished processing uploads we can show the open temp button
        if self.process_worker:
            self.open_temp_output_btn.show()
            self.text_widget.ensureCursorVisible()
        self.process_worker = None
        GSigs().wizard_set_disabled.emit(False)
        self.tracker_process_tree.setDisabled(False)

    @Slot(str, str)
    def _on_status_update(self, index: str, txt: str) -> None:
        """Used to update the `QLabel` associated with the tracker."""
        self.tracker_process_tree.update_value(index, 2, txt)

    @Slot(str)
    def _on_text_update(self, txt: str | None = None) -> None:
        """If text is provided insert it, if None or '' is sent create a line break"""
        cursor = self.text_widget.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        if txt:
            cursor.insertHtml(txt)
            LOG.info(LOG.LOG_SOURCE.FE, f"Process log: {txt}")
        if not txt:
            cursor.insertHtml("<br />")
        self.text_widget.setTextCursor(cursor)
        self.text_widget.ensureCursorVisible()

    @Slot(str)
    def _on_text_update_replace_last_line(self, txt: str) -> None:
        """Updates last line of text from the start of line"""
        cursor = self.text_widget.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(
            QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor
        )
        cursor.removeSelectedText()
        cursor.insertHtml(txt)
        self.text_widget.setTextCursor(cursor)
        self.text_widget.ensureCursorVisible()
        LOG.info(LOG.LOG_SOURCE.FE, f"Process log replace last line: {txt}")

    @Slot(str)
    def _log_caught_error(self, txt: str) -> None:
        LOG.critical(LOG.LOG_SOURCE.BE, txt)

    @Slot(float)
    def _on_progress_update(self, progress: float) -> None:
        # handle invalid progress values
        if progress is None or progress < 0:
            return

        if not self.progress_bar.isVisible():
            self.progress_bar.show()

        int_val = int(progress)
        # set progress bar to 'busy' on 0
        if int_val == 0:
            self.progress_bar.setRange(0, 0)

        # show actual progress if between 0 and 100
        elif int_val > 0 and progress < 100:
            self.progress_bar.setRange(*self._progress_bar_def_range)
            self.progress_bar.setValue(int(progress * 100))

            self.progress_bar.setTextVisible(True)
            # format text cleanly
            if progress == int_val:
                self.progress_bar.setFormat(f"{int(progress)}%")
            else:
                self.progress_bar.setFormat(f"{progress:.2f}%")

        # if complete reset and hide progress bar
        elif progress >= 100:
            self.progress_bar.reset()
            self.progress_bar.setTextVisible(False)
            self.progress_bar.hide()

        # scroll to bottom since progress bar will occupy some space depending on parent vertical size
        self.text_widget.ensureCursorVisible()

    @Slot(object)
    def _on_prompt_tokens_signal(self, tokens: Sequence[str]) -> None:
        prompt_tokens = None
        prompt = PromptTokenEditorDialog(
            items=tokens,
            warn_missing=self.config.cfg_payload.prompt_token_editor_warn_on_missing,
            parent=self,
        )
        if prompt.exec() == QDialog.DialogCode.Accepted:
            if (
                prompt.warn_on_missing.isChecked()
                != self.config.cfg_payload.prompt_token_editor_warn_on_missing
            ):
                self.config.cfg_payload.prompt_token_editor_warn_on_missing = (
                    prompt.warn_on_missing.isChecked()
                )
                self.config.save_config()
            prompt_tokens = prompt.get_results()
        GSigs().prompt_tokens_response.emit(prompt_tokens)

    @Slot(object)
    def _on_overview_signal(
        self, data: dict[TrackerSelection, dict[str | None, str]]
    ) -> None:
        result = data
        prompt = OverviewDialog(data, self)
        if prompt.exec() == QDialog.DialogCode.Accepted:
            result = prompt.get_results()
        GSigs().overview_prompt_response.emit(result)

    def _update_last_used_host(self) -> None:
        start_data = deepcopy(self.config.cfg_payload.last_used_img_host)
        for _, (
            _,
            (_, (tracker, img_dest)),
        ), _ in self.tracker_process_tree.get_item_values():
            try:
                self.config.cfg_payload.last_used_img_host[
                    TrackerSelection(tracker)
                ] = ImageHost(img_dest)
            except ValueError:
                self.config.cfg_payload.last_used_img_host[
                    TrackerSelection(tracker)
                ] = ImageSource(img_dest)
        if self.config.cfg_payload.last_used_img_host != start_data:
            self.config.save_config()

    def add_tracker_items(self) -> None:
        # sort the trackers in the users desired order before displaying them
        if self.config.shared_data.selected_trackers:
            upload_type = ImageSource.IMAGES
            enabled_img_hosts = {ImageHost.DISABLED: False}

            # if url data is detected add that to the potential options
            if self.config.shared_data.url_data:
                upload_type = ImageSource.URLS
                enabled_img_hosts = enabled_img_hosts | {
                    upload_type: self.config.shared_data.url_data
                }

            # if we have any image data, filter all image hosts that are enabled and have all required values filled
            if (
                self.config.shared_data.loaded_images
                or self.config.shared_data.url_data
            ):
                enabled_img_hosts = enabled_img_hosts | {
                    key: value
                    for key, value in self.config.image_host_map.items()
                    if value.enabled
                    and all(
                        getattr(value, field.name)
                        for field in fields(value)
                        if field.name != "enabled"
                    )
                }

            ordered_trackers = [
                x
                for x in sorted(
                    self.config.shared_data.selected_trackers,
                    key=lambda tracker: self.config.cfg_payload.tracker_order.index(
                        tracker
                    ),
                )
            ]

            for tracker in ordered_trackers:
                combo_box = self.tracker_process_tree.add_row(
                    headers=(str(tracker), "", "⌛ Queued"),
                    combo_data=[  # [int, [(str, (ImageUploadFromTo, (TrackerSelection, ImageHost)))]]
                        (
                            1,
                            [
                                (
                                    f"{upload_type} ➔ {img_host}"
                                    if img_host
                                    not in {ImageHost.DISABLED, ImageSource.URLS}
                                    else str(img_host),
                                    (
                                        ImageUploadFromTo(upload_type, img_host),
                                        (tracker, img_host),
                                    ),
                                )
                                for img_host in enabled_img_hosts.keys()
                            ],
                        )
                    ],
                )
                last_used_host = self.config.cfg_payload.last_used_img_host.get(tracker)
                if combo_box and last_used_host:
                    get_last = combo_box.findText(
                        str(last_used_host), flags=Qt.MatchFlag.MatchContains
                    )
                    if get_last != -1:
                        combo_box.setCurrentIndex(get_last)

    @Slot(QComboBox, int)
    def _tree_combo_changed(self, _combo: QComboBox, _idx: int) -> None:
        self.save_config = True

    def _handle_files(self) -> Path:
        detected_input = self.config.media_input_payload.require_input_path()
        LOG.debug(LOG.LOG_SOURCE.FE, f"Detected file input: {detected_input}")

        # handle rename if we're uploading
        if self.processing_mode is UploadProcessMode.UPLOAD:
            # grab table bg color based on theme
            table_element_bg = self.get_theme_colors()

            # new code
            payload = self.config.media_input_payload

            # iterate the renames and build out a table to show the user
            table_rows: list[str] = []
            for input_file, output_file in payload.file_list_rename_map.items():
                if str(input_file) != str(output_file):
                    table_rows.append(f"""\
                    <tr>
                        <td style="border: 1px solid #bbb; padding: 6px;">{input_file.stem}</td>
                        <td style="border: 1px solid #bbb; padding: 6px;">{output_file.stem}</td>
                    </tr>""")

            # if we have table rows lets build the table and show it in the window
            if table_rows:
                formatted_table_rows = "\n".join(table_rows)
                self._on_text_update(
                    f"""\
                    <br /><h3 style="margin: 0; padding: 0;">📼 Rename Files:</h3>
                    <table style="border-collapse: collapse; width: 100%; margin-top: 8px;">
                    <tr>
                        <th style="background: {table_element_bg}; border: 1px solid #bbb; padding: 6px; border-radius: 4px 4px 0 0;">Source</th>
                        <th style="background: {table_element_bg}; border: 1px solid #bbb; padding: 6px; border-radius: 4px 4px 0 0;">Target</th>
                    </tr>
                    {formatted_table_rows}
                    </table>"""
                )
                self._on_text_update("<br /><span>Renaming files...</span>")

                try:
                    for (
                        src_input_file,
                        trg_output_file,
                    ) in payload.file_list_rename_map.items():
                        # only rename if source and destination are different and source exists
                        if (
                            src_input_file != trg_output_file
                            and src_input_file.exists()
                        ):
                            trg_out = self.backend.rename_file(
                                f_in=src_input_file, f_out=trg_output_file
                            )
                            if not trg_out.exists():
                                detected_input_error = f"Cannot continue, the detected renamed output does not exist ({trg_out})"
                                LOG.debug(LOG.LOG_SOURCE.FE, detected_input_error)
                                raise ProcessError(detected_input_error)
                except Exception as e:
                    LOG.error(
                        LOG.LOG_SOURCE.FE,
                        f"Failed to rename file: {e}\n{traceback.format_exc()}",
                    )
                    raise
                self._on_text_update("<br /><span>Renaming files completed</span>")

            # TODO: handle directory renaming

            # new code

            # # file rename first (if needed)
            # if renamed_input and (str(og_input) != str(renamed_input)):
            #     self._on_text_update(f"""\
            #         <br /><h3 style="margin: 0; padding: 0;">📼 Renaming input file:</h3>
            #         <table style="border-collapse: collapse; width: 100%; margin-top: 8px;">
            #         <tr>
            #             <th style="background: {table_element_bg}; border: 1px solid #bbb; padding: 6px; border-radius: 4px 4px 0 0;">Original</th>
            #             <th style="background: {table_element_bg}; border: 1px solid #bbb; padding: 6px; border-radius: 4px 4px 0 0;">Renamed</th>
            #         </tr>
            #         <tr>
            #             <td style="border: 1px solid #bbb; padding: 6px;">{og_input.stem}</td>
            #             <td style="border: 1px solid #bbb; padding: 6px;">{renamed_input.stem}</td>
            #         </tr>
            #         </table>""")
            #     try:
            #         # only rename if source and destination are different and source exists
            #         if og_input != renamed_input and og_input.exists():
            #             detected_input = self.backend.rename_file(
            #                 f_in=og_input, f_out=renamed_input
            #             )
            #             if not detected_input.exists():
            #                 detected_input_error = (
            #                     "Cannot continue, the detected input does not exist"
            #                 )
            #                 LOG.debug(LOG.LOG_SOURCE.FE, detected_input_error)
            #                 raise ProcessError(detected_input_error)
            #             # update payload to reflect new file name
            #             self.config.media_input_payload.encode_file = detected_input
            #             og_input = detected_input
            #         else:
            #             detected_input = renamed_input
            #             self.config.media_input_payload.encode_file = detected_input
            #             og_input = detected_input
            #     except Exception as e:
            #         LOG.error(
            #             LOG.LOG_SOURCE.FE,
            #             f"Failed to rename file: {e}\n{traceback.format_exc()}",
            #         )
            #         raise

            # # directory rename (if needed)
            # if encode_file_dir:
            #     # The new folder name should be detected_input.stem
            #     new_folder = encode_file_dir.parent / detected_input.stem
            #     if encode_file_dir != new_folder:
            #         try:
            #             self._on_text_update(f"""\
            #                 <br /><h3 style="margin: 0; padding: 0;">📂 Renaming parent folder:</h3>
            #                 <table style="border-collapse: collapse; width: 100%; margin-top: 8px;">
            #                 <tr>
            #                     <th style="background: {table_element_bg}; border: 1px solid #bbb; padding: 6px; border-radius: 4px 4px 0 0;">Original</th>
            #                     <th style="background: {table_element_bg}; border: 1px solid #bbb; padding: 6px; border-radius: 4px 4px 0 0;">Renamed</th>
            #                 </tr>
            #                 <tr>
            #                     <td style="border: 1px solid #bbb; padding: 6px;">{encode_file_dir.stem}</td>
            #                     <td style="border: 1px solid #bbb; padding: 6px;">{new_folder.stem}</td>
            #                 </tr>
            #                 </table>""")
            #             encode_file_dir.rename(new_folder)
            #             # update payload to reflect new folder name
            #             self.config.media_input_payload.encode_file_dir = new_folder
            #             encode_file_dir = new_folder
            #             # update encode_file path to point to the file inside the new folder
            #             old_file = self.config.media_input_payload.encode_file
            #             if old_file:
            #                 new_file = new_folder / Path(old_file).name
            #                 self.config.media_input_payload.encode_file = new_file
            #                 detected_input = new_file
            #         except Exception as e:
            #             LOG.error(
            #                 LOG.LOG_SOURCE.FE,
            #                 f"Failed to rename parent folder: {e}\n{traceback.format_exc()}",
            #             )
            #             raise

        # return detected_input, mediainfo_obj, encode_file_dir
        return detected_input

    def _gather_tracker_data(self, detected_input: Path) -> dict[str, Any] | None:
        process_dir = self.config.media_input_payload.working_dir
        if not process_dir:
            raise ValueError("Failed to detect MediaInputPayload.working_dir")

        # build data
        tracker_data = {}
        for tracker, (
            combo_text,
            (image_host_data, _),
        ), _ in self.tracker_process_tree.get_item_values():
            process_dir_out = process_dir / tracker.lower()
            process_dir_out.mkdir(parents=True, exist_ok=True)
            torrent_out = Path(process_dir_out / f"{detected_input.stem}.torrent")

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
                            dir=str(process_dir_out) if process_dir_out else "",
                        )
                        if not new_torrent_out:
                            return
                        torrent_out = Path(new_torrent_out)
            tracker_data[tracker] = {
                "path": torrent_out,
                "image_host": combo_text,
                "image_host_data": image_host_data,
            }

        if not tracker_data:
            tracker_paths_error_msg = "Failed to generate tracker data"
            LOG.error(LOG.LOG_SOURCE.FE, tracker_paths_error_msg)
            raise ProcessError(tracker_paths_error_msg)

        return tracker_data

    def get_theme_colors(self):
        app = QApplication.instance()
        if app:
            color_scheme = app.styleHints().colorScheme()  # pyright: ignore [reportAttributeAccessIssue, reportOptionalMemberAccess]
            scheme = "dark" if color_scheme == Qt.ColorScheme.Dark else "light"
            return self.THEMES[scheme]["box_color"]
        return "#e6e6e6"

    @Slot()
    def _open_temp_output(self) -> None:
        if (
            self.config.media_input_payload.working_dir
            and self.config.media_input_payload.working_dir.exists()
        ):
            open_explorer(self.config.media_input_payload.working_dir)

    def initializePage(self) -> None:
        self.add_tracker_items()

    @Slot()
    def reset_page(self) -> None:
        self.save_config = False
        self.processing_mode = UploadProcessMode.DUPE_CHECK
        self.dupe_worker = None
        self.process_worker = None
        self.tracker_process_tree.clear()
        self.text_widget.clear()
        self.progress_bar.reset()
        self.progress_bar.hide()
        self.open_temp_output_btn.hide()
