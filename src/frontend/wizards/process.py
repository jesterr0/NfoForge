import asyncio
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import fields
from html import escape
from pathlib import Path
import shutil
import traceback
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import Qt, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from src.backend.jobs import (
    JobAssetError,
    JobCodecError,
    JobStoreError,
    JobSummary,
    base_torrent_snapshot,
    build_job,
    capture_mediainfo,
    capture_nfos,
    context_to_dict,
    copy_base_torrent,
    copy_images,
    filter_context_document,
    fingerprint_files,
    job_dir,
    load_job,
    mediainfo_sources,
    prune_unreferenced_nfos,
    rebuild_job_document,
    save_job,
    torrent_content_files,
    write_job_document,
)
from src.backend.process import ProcessBackEnd
from src.backend.torrents import BASE_TORRENT_SUFFIX
from src.backend.tracker_run_data import build_tracker_data, image_host_label
from src.backend.upload_retry import (
    TrackerRunOutcome,
    UploadFailure,
    UploadFailurePhase,
    UploadRetryAction,
)
from src.backend.utils.file_utilities import open_explorer, release_stem
from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.enums.image_host import ImageHost, ImageSource
from src.enums.tracker_selection import TrackerSelection
from src.enums.upload_process import RunPhase, UploadProcessMode
from src.exceptions import ProcessCancelled, ProcessError
from src.frontend.custom_widgets.combo_qtree import ComboBoxTreeWidget
from src.frontend.custom_widgets.overview_dialog import OverviewDialog
from src.frontend.custom_widgets.prompt_token_editor_dialog import (
    PromptTokenEditorDialog,
)
from src.frontend.global_signals import GSigs
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.logger.nfo_forge_logger import LOG
from src.packages.custom_types import ImageUploadData, ImageUploadFromTo
from src.payloads.image_hosts import ImagePayloadBase
from src.payloads.tracker_search_result import TrackerSearchResult
from src.utils.secret_redaction import scrub_secrets

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


def _measure_content_size(input_path: Path) -> int | None:
    """Total bytes of the release, or None when it cannot be measured.

    Matches what a generated torrent reports (`Torrent.size`), so a job that
    has a base torrent and one that does not record the same number: the sum of
    every file for a pack, the file's own size for a single file. `stat()` on a
    directory would report the directory entry instead, which is not a release
    size at all.
    """
    try:
        if input_path.is_dir():
            return sum(
                path.stat().st_size for path in torrent_content_files(input_path)
            )
        return input_path.stat().st_size if input_path.is_file() else None
    except OSError as error:
        LOG.warning(
            LOG.LOG_SOURCE.FE,
            f"Could not measure the size of '{input_path}' for this job: {error}",
        )
        return None


_SOURCE_LESS_TEXT = (
    "The original media is not available. Using the archived release package; "
    "configured plugins and torrent clients will still be attempted. This does "
    "not recreate the media, so ensure the content still exists where your "
    "torrent client will seed it."
)
"""Shown when a run has no source left and is riding on its archived torrent."""


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
        context: ProcessingContext,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.context = context
        self.processing_queue = processing_queue

    def run(self) -> None:
        async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(async_loop)
        try:
            dupes = async_loop.run_until_complete(
                self.backend.dupe_checks(
                    processing_queue=self.processing_queue,
                    media_input_payload=self.context.media_input,
                    media_search_payload=self.context.media_search,
                )
            )
            self.results.emit(dupes)
        except Exception as e:
            self.job_failed.emit(str(e), traceback.format_exc())
        finally:
            async_loop.close()


class _TokenPromptWaiter(QObject):
    """Bound-method receiver for ``prompt_tokens_response``.

    PySide routes a queued connection to a plain Python closure through an
    internal receiver whose thread affinity is pinned by the *first*
    connection made in the process. On a second (or later) worker QThread
    that pins the delivery to the wrong thread and the signal is silently
    dropped. A fresh QObject instance per call carries its own thread
    affinity, so real bound ``@Slot`` methods on it keep being delivered.
    """

    def __init__(self, worker: "ProcessWorker", loop: QEventLoop) -> None:
        super().__init__()
        self._worker = worker
        self._loop = loop

    @Slot(object)
    def on_response(self, response: dict[str, str] | None) -> None:
        self._worker._prompt_tokens_response = response
        self._loop.quit()


class _OverviewPromptWaiter(QObject):
    """Bound-method receiver for ``overview_prompt_response``. See
    ``_TokenPromptWaiter`` for why a closure slot is not used here."""

    def __init__(self, worker: "ProcessWorker", loop: QEventLoop) -> None:
        super().__init__()
        self._worker = worker
        self._loop = loop

    @Slot(object)
    def on_response(
        self, response: dict[TrackerSelection, dict[str, str | None]] | None
    ) -> None:
        self._worker._overview_prompt = response
        self._loop.quit()


class _UploadRetryWaiter(QObject):
    """Bound-method receiver for ``upload_retry_ack`` / ``upload_retry_response``.
    See ``_TokenPromptWaiter`` for why a closure slot is not used here."""

    def __init__(self, watchdog: QTimer, loop: QEventLoop) -> None:
        super().__init__()
        self._watchdog = watchdog
        self._loop = loop
        self.response: UploadRetryAction | None = None

    @Slot()
    def on_ack(self) -> None:
        self._watchdog.stop()

    @Slot(object)
    def on_response(self, action: UploadRetryAction) -> None:
        self.response = action
        self._loop.quit()


class ProcessWorker(BaseWorker):
    queued_status_update = Signal(str, str)
    progress_signal = Signal(float)
    prompt_tokens_signal = Signal(list)
    overview_signal = Signal(object)
    upload_retry_signal = Signal(object)
    run_outcome_signal = Signal(object, object)  # TrackerSelection, TrackerRunOutcome
    job_cancelled = Signal()

    RETRY_PROMPT_ACK_TIMEOUT_MS = 5000

    def __init__(
        self,
        backend: ProcessBackEnd,
        tracker_data: dict[str, Any],
        context: ProcessingContext,
        phase: RunPhase = RunPhase.FULL,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.tracker_data = tracker_data
        self.context = context
        self.phase = phase

        self._prompt_tokens_response: dict[str, str] | None = None
        self._overview_prompt: dict[TrackerSelection, dict[str, str | None]] | None = (
            None
        )

    def run(self) -> None:
        try:
            self.backend.process_trackers(
                process_dict=self.tracker_data,
                queued_status_update=self._queued_status_update_cb,
                queued_text_update=self._queued_text_update_cb,
                queued_text_update_replace_last_line=self._queued_text_update_replace_last_line_cb,
                progress_bar_cb=self._progress_cb,
                caught_error=self.caught_error,
                context=self.context,
                token_prompt_cb=self.token_prompt_and_wait_cb,
                overview_cb=self.overview_prompt_and_wait_cb,
                upload_retry_cb=self.upload_retry_and_wait_cb,
                run_outcome_cb=self._run_outcome_cb,
                phase=self.phase,
            )
            self.job_finished.emit()
        except ProcessCancelled:
            self.job_cancelled.emit()
        except Exception as e:
            self.job_failed.emit(
                f"Failed to process trackers: {e}", traceback.format_exc()
            )

    def _run_outcome_cb(
        self, tracker: TrackerSelection, outcome: TrackerRunOutcome
    ) -> None:
        self.run_outcome_signal.emit(tracker, outcome)

    def _queued_status_update_cb(self, tracker: str, status: str) -> None:
        if tracker and status:
            self.queued_status_update.emit(tracker, status)

    def _progress_cb(self, progress: float) -> None:
        if progress is not None:
            self.progress_signal.emit(progress)

    def token_prompt_and_wait_cb(
        self, tokens: Sequence[str] | None
    ) -> dict[str, str] | None:
        if not tokens:
            return None

        self._prompt_tokens_response = None
        self.prompt_tokens_signal.emit(tokens)
        # start event loop
        loop = QEventLoop()
        waiter = _TokenPromptWaiter(self, loop)

        # wait for response
        GSigs().prompt_tokens_response.connect(waiter.on_response)
        try:
            loop.exec_()
        finally:
            GSigs().prompt_tokens_response.disconnect(waiter.on_response)

        # return response
        return self._prompt_tokens_response

    def overview_prompt_and_wait_cb(
        self, data: dict[TrackerSelection, dict[str, str | None]] | None
    ) -> dict[TrackerSelection, dict[str, str | None]] | None:
        if not data:
            return None

        self._overview_prompt = None
        self.overview_signal.emit(data)

        # start loop
        loop = QEventLoop()
        waiter = _OverviewPromptWaiter(self, loop)

        # wait for response
        GSigs().overview_prompt_response.connect(waiter.on_response)
        try:
            loop.exec_()
        finally:
            GSigs().overview_prompt_response.disconnect(waiter.on_response)

        # return response
        return self._overview_prompt

    def upload_retry_and_wait_cb(self, failure: UploadFailure) -> UploadRetryAction:
        """Ask the frontend what to do with a failed tracker upload."""
        loop = QEventLoop()

        # The GUI may be gone: if the slot is never invoked nothing would ever
        # reply and this loop would block forever. Bound the wait until the GUI
        # acknowledges receipt, then let the user take as long as they need.
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)

        waiter = _UploadRetryWaiter(watchdog, loop)

        # Connect before emitting so the response can never arrive first, and
        # always disconnect so a raise inside the loop cannot leak a connection
        # onto the global signal singleton.
        GSigs().upload_retry_ack.connect(waiter.on_ack)
        GSigs().upload_retry_response.connect(waiter.on_response)
        try:
            watchdog.start(self.RETRY_PROMPT_ACK_TIMEOUT_MS)
            self.upload_retry_signal.emit(failure)
            loop.exec_()
        finally:
            watchdog.stop()
            GSigs().upload_retry_response.disconnect(waiter.on_response)
            GSigs().upload_retry_ack.disconnect(waiter.on_ack)

        return waiter.response or UploadRetryAction.CANCEL


class ProcessPage(BaseWizardPage):
    THEMES = {
        "dark": {"box_color": "#626262"},
        "light": {"box_color": "#e6e6e6"},
    }

    def __init__(
        self, config: ConfigManager, context: ProcessingContext, parent: "MainWindow"
    ) -> None:
        super().__init__(config, context, parent)
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

        # Per-run only, and deliberately not on the payload: this must never
        # reach a job file. It answers which trackers may still be uploaded
        # once a run ends, so the remainder can be deferred into a new job.
        self._run_outcomes: dict[TrackerSelection, TrackerRunOutcome] = {}
        self._run_phase = RunPhase.FULL

        # The notice below describes the run as a whole rather than something
        # that happened, so it is latched: `process_jobs` is entered once per
        # press of the Process button (dupe check, then upload, and again for
        # Prepare), and repeating it there reads as spam.
        self._source_less_notice_shown = False

        self.source_less_banner = QLabel(self, wordWrap=True)
        self.source_less_banner.setText(f"⚠ {_SOURCE_LESS_TEXT}")
        # Text and border only: the pane is themed by the app, and painting a
        # background here would fight whichever theme is active.
        self.source_less_banner.setStyleSheet(
            "color: #d68c00; border: 1px solid #d68c00; border-radius: 4px; "
            "padding: 6px;"
        )
        self.source_less_banner.hide()

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

        self.save_job_btn = QPushButton("Save Job", self)
        self.save_job_btn.setToolTip(
            "Saves this configured upload so it can be loaded and processed later"
        )
        self.save_job_btn.clicked.connect(self._save_job)

        self.prepare_job_btn = QPushButton("Prepare && Save Job", self)
        self.prepare_job_btn.setToolTip(
            "Uploads images and generates the torrent, titles and NFOs now, then "
            "saves a job that only needs uploading -- it will not ask anything "
            "when it is run"
        )
        self.prepare_job_btn.clicked.connect(self._prepare_job)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.save_job_btn)
        button_row.addWidget(self.prepare_job_btn)
        button_row.addWidget(self.open_temp_output_btn)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.source_less_banner)
        main_layout.addWidget(self.tracker_process_tree, stretch=3)
        main_layout.addWidget(text_widget_label, alignment=Qt.AlignmentFlag.AlignBottom)
        main_layout.addWidget(self.text_widget, stretch=5)
        main_layout.addWidget(self.progress_bar, stretch=1)
        main_layout.addLayout(button_row)
        self.setLayout(main_layout)

    def _source_less_run(self) -> bool:
        """Whether this run is riding on its archive rather than on the media.

        The same condition `process_jobs` acts on, kept in one place so the
        banner and the log line can never disagree about it.
        """
        if self.context.shared_data.base_torrent is None:
            return False
        try:
            self.context.media_input.require_existing_media_paths(
                include_comparison=False
            )
        except (FileNotFoundError, RuntimeError):
            return True
        return False

    def _announce_saved_job(self, name: str) -> None:
        """Note a save in the log pane.

        Escaped because the name is free text from a prompt, and the pane
        renders HTML -- an unescaped `<` silently swallows the rest of the line.
        """
        self._on_text_update(
            f"<br /><span>💾 Saved job '{escape(name)}'. Load it from the start "
            "page to process it later.</span>"
        )

    @Slot()
    def _save_job(self, keep_trackers: set[TrackerSelection] | None = None) -> None:
        """Persist this configured run so it can be processed later.

        Deliberately does not dupe check: results would be stale by the time
        the job is actually run, so that check stays where it is, immediately
        before uploading.

        `keep_trackers` narrows the job to a subset, which is how a partially
        completed run is deferred -- the trackers that already uploaded are
        left out entirely rather than being marked as done, so the saved job
        cannot re-upload them.
        """
        media_input = self.context.media_input
        input_path = media_input.require_input_path()
        media_input.input_kind = "directory" if input_path.is_dir() else "file"
        try:
            # capturing MediaInfo reads every input file, so the comparison
            # source has to be there too when one is in play
            media_input.require_existing_media_paths(
                include_comparison=bool(media_input.comparison_pair)
            )
        except (FileNotFoundError, RuntimeError) as error:
            QMessageBox.critical(
                self,
                "Media Files Unavailable",
                f"This job cannot be saved because its input paths are no longer "
                f"valid:\n\n{error}",
            )
            return

        default_name = self._default_job_name()
        name, accepted = self._get_job_name(default_name)
        if not accepted:
            return

        working_dir = self.config.settings.general.working_dir
        job = build_job(
            name=name or default_name,
            summary=self._job_summary(keep_trackers),
            context={},
            config_profile=self.config.program.current_config,
        )
        directory = job_dir(working_dir, job.job_id, ensure_exists=True)

        try:
            document = self._build_job_document(directory, keep_trackers)
            job.context = document
            job_path = save_job(job, working_dir)
        except (JobCodecError, JobStoreError, JobAssetError, OSError) as error:
            LOG.error(LOG.LOG_SOURCE.FE, f"Failed to save job: {error}")
            # the directory only holds half-captured assets at this point and
            # has no job.json, so remove it rather than leaving a stub behind
            shutil.rmtree(directory, ignore_errors=True)
            QMessageBox.critical(self, "Save Failed", f"Could not save job:\n\n{error}")
            return

        self._announce_saved_job(job.name)
        saved_box = QMessageBox(self)
        saved_box.setWindowTitle("Job Saved")
        # PlainText rather than the default AutoText: the job name is free text
        # from a prompt, and one containing angle brackets would otherwise flip
        # the box into rich-text mode, swallowing the name and collapsing the
        # line breaks below it. Escaping is not the fix here -- it would show
        # the entities literally instead of the name the user typed.
        saved_box.setTextFormat(Qt.TextFormat.PlainText)
        saved_box.setIcon(QMessageBox.Icon.Information)
        saved_box.setText(
            f"Saved '{job.name}'.\n\nUse 'Jobs' on the start page to come "
            f"back to it.\n\n{job_path}"
        )
        saved_box.exec()

    def _get_job_name(self, cur_name: str | None) -> tuple[str, bool]:
        """Dialog to gather save job name."""
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Save Job")
        dlg.setLabelText("Job name:")

        if cur_name:
            dlg.setTextValue(cur_name)

        dlg.resize(400, dlg.sizeHint().height())

        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        if not accepted:
            return "", False

        return dlg.textValue().strip(), True

    def _build_job_document(
        self, directory: Path, keep_trackers: set[TrackerSelection] | None
    ) -> dict[str, Any]:
        """Capture the job's assets, then serialize it pointing at those copies.

        Everything a resumed run needs is copied beside the job so it stops
        depending on `processing/`, which Clean Up is meant to empty. When
        `keep_trackers` is given, only the NFOs for those trackers are
        captured -- a narrowed job must not keep sidecars for trackers it no
        longer covers.
        """
        media_input = self.context.media_input
        input_path = media_input.require_input_path()
        media_input.input_kind = "directory" if input_path.is_dir() else "file"
        # Recorded whether or not a torrent was generated. Without it the two
        # trackers that size a disc release fall back to reading the input path
        # off the filesystem (`beyondhd.py`, `passthepopcorn.py`), which a
        # source-less run cannot do -- and this is the last moment the media is
        # guaranteed to be there to measure.
        if media_input.content_size is None:
            media_input.content_size = _measure_content_size(input_path)

        # MediaInfo is captured for every object the context can reach, not
        # just the run's own file list: a plugin holding a per-episode source
        # MediaInfo needs its dump stored too, or a resumed run has nothing to
        # rebuild it from
        mediainfo_assets = capture_mediainfo(
            directory, list(mediainfo_sources(self.context))
        )

        # copied even when the images already uploaded and their URLs were
        # recorded: changing a tracker's image host on resume invalidates those
        # URLs and needs the local files back
        copied_images = copy_images(
            directory,
            [Path(image) for image in (self.context.shared_data.loaded_images or ())],
        )

        base_torrent = self._first_generated_torrent()
        snapshot: dict[str, Any] | None = None
        if base_torrent:
            copy_base_torrent(directory, base_torrent)
            snapshot = base_torrent_snapshot(base_torrent)
            media_input.content_size = cast(int, snapshot["content_size"])

        # a prepared job's NFOs are the ones that get uploaded, so they cannot
        # be left in `processing/` where Clean Up would take them -- and a
        # narrowed job must not keep sidecars for trackers it no longer covers
        release_data = self.context.shared_data.tracker_release_data
        if keep_trackers is not None:
            release_data = {
                tracker: release
                for tracker, release in release_data.items()
                if tracker in keep_trackers
            }
        nfo_assets = capture_nfos(directory, release_data)

        document = context_to_dict(self.context, mediainfo_assets, nfo_assets)
        if copied_images:
            document["shared_data"]["loaded_images"] = [
                str(image) for image in copied_images
            ]
        if base_torrent:
            if snapshot is None:
                raise JobAssetError("Could not capture the base torrent snapshot")
            document["base_torrent"] = {
                "media": str(input_path),
                "snapshot": snapshot,
                # every file, not just the first: the torrent is built from
                # `input_path`, so one file of a pack cannot vouch for the rest
                "fingerprints": fingerprint_files(torrent_content_files(input_path)),
            }
        if keep_trackers is not None:
            document = filter_context_document(document, keep_trackers)
        return document

    def _first_generated_torrent(self) -> Path | None:
        """The neutral base this run hashed, usable as a clone source.

        Hashing the media is the single most expensive step, so a job that can
        carry a finished torrent lets a later run skip it entirely.

        Only the base will do. The tracker torrents one level down are stamped
        with a tracker's announce, source and comment, and a UNIT3D one is
        additionally whatever that tracker's server handed back on upload --
        carrying any of those forward would seed the next run from one
        tracker's artifact. `_prepare_base_torrent` always writes the base
        here, including when the run itself reused a carried one, so this is
        the single place to look.
        """
        working_dir = self.context.media_input.working_dir
        input_path = self.context.media_input.input_path
        if not working_dir or not input_path:
            return None
        base = working_dir / (
            f"{release_stem(input_path, self.context.media_input.input_is_directory())}"
            f"{BASE_TORRENT_SUFFIX}"
        )
        return base if base.is_file() else None

    def _default_job_name(self) -> str:
        """Best available human name for this release."""
        title = self.context.media_search.title
        if title:
            year = self.context.media_search.year
            return f"{title} ({year})" if year else title
        input_path = self.context.media_input.input_path
        return input_path.stem if input_path else "Untitled job"

    def _job_summary(
        self, keep_trackers: set[TrackerSelection] | None = None
    ) -> JobSummary:
        input_path = self.context.media_input.input_path
        media_type = self.context.media_input.media_type
        return JobSummary(
            title=self.context.media_search.title,
            year=self.context.media_search.year,
            media_type=str(media_type) if media_type else None,
            input_name=input_path.name if input_path else None,
            input_path=str(input_path) if input_path else "",
            file_count=len(self.context.media_input.file_list),
            # `keep_trackers` is the authority when given. Filtering the run's
            # image-host map by it would drop a tracker the run never touched --
            # one left pending by an earlier run, whose row does not exist this
            # time -- and the summary is what the picker shows and what decides
            # whether a saved job can still be opened.
            trackers=sorted(str(tracker) for tracker in keep_trackers)
            if keep_trackers is not None
            else [
                str(tracker) for tracker in self.context.shared_data.tracker_image_hosts
            ],
        )

    @Slot()
    def process_jobs(self) -> None:
        try:
            self.context.media_input.require_existing_media_paths(
                include_comparison=False
            )
        except (FileNotFoundError, RuntimeError) as error:
            if self.context.shared_data.base_torrent is None:
                QMessageBox.critical(
                    self,
                    "Media Files Unavailable",
                    f"Processing cannot start because its input paths are no longer "
                    f"valid:\n\n{error}",
                )
                return
            if not self._source_less_notice_shown:
                self._source_less_notice_shown = True
                self._on_text_update(
                    f"<span style='color: #d68c00;'>{_SOURCE_LESS_TEXT}</span>"
                    "<br /><br />"
                )

        # Nothing to upload to is a state the user can reach -- a job that has
        # already been everywhere it was run for -- so it is answered here
        # rather than left to fail as an unhandled exception further down.
        if not self.context.shared_data.tracker_image_hosts:
            QMessageBox.warning(
                self,
                "No Trackers",
                "This run has no trackers to upload to.\n\nIf this came from a "
                "saved job, reopen it from the Jobs dialog with 'Add Trackers' "
                "to choose one, or use 'Start Over' to begin a new run.",
            )
            return

        # get paths and other things from the media input payload
        detected_input = self.context.media_input.require_input_path()
        LOG.debug(LOG.LOG_SOURCE.FE, f"Detected file input: {detected_input}")

        # get tracker data and check for existing torrent files
        tracker_data = self._gather_tracker_data(detected_input)
        if not tracker_data:
            # None means the overwrite prompt was backed out of, which is the
            # user cancelling rather than anything going wrong.
            return

        GSigs().wizard_set_disabled.emit(True)
        self.tracker_process_tree.setDisabled(True)
        self.save_job_btn.setDisabled(True)
        self.prepare_job_btn.setDisabled(True)

        if self.processing_mode is UploadProcessMode.DUPE_CHECK:
            self.dupe_worker = DupeWorker(
                backend=self.backend,
                processing_queue=[TrackerSelection(x) for x in tracker_data.keys()],
                context=self.context,
                parent=self,
            )
            self.dupe_worker.results.connect(self._on_dupe_results)
            self.dupe_worker.job_failed.connect(self._on_dupes_failed)
            self._on_text_update(
                '<h3 style="margin: 0; padding: 0;">📋 Checking for dupes:</h3>',
            )
            self.dupe_worker.start()

        elif self.processing_mode is UploadProcessMode.PREPARE:
            self._start_process_worker(tracker_data, RunPhase.PREPARE)

        elif self.processing_mode is UploadProcessMode.UPLOAD:
            self._start_process_worker(tracker_data, RunPhase.FULL)

    def _start_process_worker(
        self, tracker_data: dict[str, Any], phase: RunPhase
    ) -> None:
        """Run the pipeline, either all the way through or stopping before upload."""
        if self.save_config:
            self.save_config = False
            self._update_last_used_host()

        if not self.context.media_search.media_type:
            raise AttributeError("Failed to determine MediaType")

        # every tracker starts unattempted; the run overwrites each as it
        # resolves, so a run that dies early still leaves an accurate map
        self._run_outcomes = {
            TrackerSelection(name): TrackerRunOutcome.NOT_ATTEMPTED
            for name in tracker_data
        }
        self._run_phase = phase

        self.process_worker = ProcessWorker(
            backend=self.backend,
            tracker_data=tracker_data,
            context=self.context,
            phase=phase,
            parent=self,
        )
        self.process_worker.caught_error.connect(self._log_caught_error)
        self.process_worker.job_finished.connect(self._on_finished)
        self.process_worker.job_cancelled.connect(self._on_cancelled)
        self.process_worker.queued_status_update.connect(self._on_status_update)
        self.process_worker.progress_signal.connect(self._on_progress_update)
        self.process_worker.job_failed.connect(self._on_failed)
        self.process_worker.queued_text_update.connect(self._on_text_update)
        self.process_worker.queued_text_update_replace_last_line.connect(
            self._on_text_update_replace_last_line
        )
        self.process_worker.prompt_tokens_signal.connect(self._on_prompt_tokens_signal)
        self.process_worker.overview_signal.connect(self._on_overview_signal)
        self.process_worker.upload_retry_signal.connect(self._on_upload_retry_signal)
        self.process_worker.run_outcome_signal.connect(self._on_run_outcome)
        self.process_worker.start()

    @Slot(object, object)
    def _on_run_outcome(
        self, tracker: TrackerSelection, outcome: TrackerRunOutcome
    ) -> None:
        self._run_outcomes[tracker] = outcome

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
    def _prepare_job(self) -> None:
        """Run everything except upload, then save the result as a job."""
        if (
            QMessageBox.question(
                self,
                "Prepare Job",
                "This uploads your screenshots and generates the torrent, titles "
                "and NFOs now, then saves a job that only needs uploading.\n\n"
                "It can take a while. Continue?",
            )
            is not QMessageBox.StandardButton.Yes
        ):
            return
        self.processing_mode = UploadProcessMode.PREPARE
        self.process_jobs()

    @Slot()
    def _on_finished(self) -> None:
        prepared = self._run_phase is RunPhase.PREPARE
        self._job_ended()
        if prepared:
            # nothing was uploaded, so this run ends in a save rather than in
            # the deferred-job offer
            self.processing_mode = UploadProcessMode.DUPE_CHECK
            self._on_text_update("<br /><span>📦 Prepared. Saving this job...</span>")
            if not self._save_prepared_archive():
                self._save_job()
            return
        GSigs().wizard_process_btn_set_hidden.emit()
        archive_completed = getattr(self, "_archive_completed_run", None)
        if not callable(archive_completed) or not archive_completed():
            self._offer_deferred_job()

    @Slot()
    def _on_cancelled(self) -> None:
        self._job_ended()
        self._on_text_update(
            "<br /><span style='font-weight: bold;'>Remaining processing cancelled. "
            "Trackers that already completed were not rolled back; restart the "
            "wizard to upload the remaining ones.</span>"
        )
        # Without this the process button restarts from the first tracker and
        # re-uploads the ones that already succeeded.
        GSigs().wizard_process_btn_set_hidden.emit()
        archive_completed = getattr(self, "_archive_completed_run", None)
        if not callable(archive_completed) or not archive_completed():
            self._offer_deferred_job()

    @Slot(str, str)
    def _on_failed(self, e: str, trace_back: str) -> None:
        self._job_ended()
        self._on_text_update(f"<br /><p>{scrub_secrets(e)}</p>")
        LOG.error(LOG.LOG_SOURCE.FE, scrub_secrets(trace_back))
        archive_completed = getattr(self, "_archive_completed_run", None)
        if not callable(archive_completed) or not archive_completed():
            self._offer_deferred_job()

    def _archive_completed_run(self) -> bool:
        """Persist one reusable archive and reconcile tracker outcomes into it."""
        if self._run_phase is not RunPhase.FULL or not self._run_outcomes:
            return False

        landed = {
            tracker
            for tracker, outcome in self._run_outcomes.items()
            if outcome
            in {TrackerRunOutcome.UPLOADED, TrackerRunOutcome.INJECTION_FAILED}
        }
        uncertain = {
            tracker
            for tracker, outcome in self._run_outcomes.items()
            if outcome is TrackerRunOutcome.MAY_HAVE_UPLOADED
        }
        context = self.context
        working_dir = self.config.settings.general.working_dir
        existing_path = context.loaded_job_path
        creating = existing_path is None
        created_directory: Path | None = None
        try:
            if existing_path is not None:
                job = load_job(existing_path)
                directory = existing_path
            else:
                job = build_job(
                    name=self._default_job_name(),
                    summary=JobSummary(),
                    context={},
                    config_profile=self.config.program.current_config,
                    archived=True,
                )
                directory = job_dir(working_dir, job.job_id, ensure_exists=True)
                created_directory = directory

            uploaded_all = context.loaded_uploaded_trackers | landed
            uncertain_all = (context.loaded_uncertain_trackers | uncertain) - landed
            # A tracker left pending by an *earlier* run is not in
            # `_run_outcomes`, but its prepared title and NFO are still on the
            # context. Narrowing to only this run's leftovers would drop them
            # from the document, and `prune_unreferenced_nfos` would then
            # delete the sidecars -- silently discarding prepared work whose
            # only way back is preparing that tracker over again.
            pending = (
                (
                    set(self._run_outcomes)
                    | set(context.shared_data.tracker_release_data)
                )
                - uploaded_all
                - uncertain_all
            )

            if creating:
                document = self._build_job_document(directory, None)
            else:
                document = rebuild_job_document(job, directory, context)

            # An uncertain tracker keeps its title, NFO and image state while
            # staying out of `selected_trackers`, so nothing can resume into a
            # second upload -- and resolving it as "never landed" has the
            # prepared work to put back. Narrowing it away instead left only
            # its name, and offered a resolution the data could not support.
            document = filter_context_document(
                document, pending, retain_data_for=uncertain_all
            )
            job.context = document
            job.archived = True
            job.uploaded_trackers = sorted(tracker.name for tracker in uploaded_all)
            job.uncertain_trackers = sorted(tracker.name for tracker in uncertain_all)
            job.summary = self._job_summary(pending)
            job.summary.uploaded_trackers = sorted(
                str(tracker) for tracker in uploaded_all
            )
            job.summary.uncertain_trackers = sorted(
                str(tracker) for tracker in uncertain_all
            )
            write_job_document(job, directory)
            try:
                prune_unreferenced_nfos(directory, job.context)
            except OSError as error:
                LOG.warning(
                    LOG.LOG_SOURCE.FE,
                    f"Archive saved but stale NFO cleanup failed: {error}",
                )

            context.loaded_job_path = directory
            context.loaded_job_id = job.job_id
            context.loaded_job_name = job.name
            context.loaded_job_archived = True
            context.loaded_uploaded_trackers = uploaded_all
            context.loaded_uncertain_trackers = uncertain_all
            self._on_text_update(
                f"<br /><span>📦 Archived '{escape(job.name)}' for future "
                "trackers.</span>"
            )
            return True
        except (JobAssetError, JobCodecError, JobStoreError, OSError) as error:
            LOG.error(LOG.LOG_SOURCE.FE, f"Failed to archive completed run: {error}")
            if created_directory is not None:
                shutil.rmtree(created_directory, ignore_errors=True)
            QMessageBox.warning(
                self,
                "Archive Failed",
                "The upload run finished, but its reusable job archive could not "
                f"be saved:\n\n{error}",
            )
            return False

    def _save_prepared_archive(self) -> bool:
        """Update a loaded archive after preparing newly added trackers.

        Only an archive takes this path. Preparing an ordinary saved job keeps
        the named save it always had -- silently overwriting the job the user
        opened is not what "Prepare Job" has ever meant, and that job still has
        its media, so `_save_job` can capture MediaInfo the normal way. An
        archive cannot: it may have no source left, which is what the stored
        assets below are for.
        """
        if not self.context.loaded_job_archived:
            return False
        path = self.context.loaded_job_path
        if path is None:
            return False
        try:
            job = load_job(path)
            job.context = rebuild_job_document(job, path, self.context)
            job.summary = self._job_summary()
            job.summary.uploaded_trackers = sorted(
                str(tracker) for tracker in self.context.loaded_uploaded_trackers
            )
            job.summary.uncertain_trackers = sorted(
                str(tracker) for tracker in self.context.loaded_uncertain_trackers
            )
            write_job_document(job, path)
            self._on_text_update(
                f"<br /><span>📦 Updated prepared archive '{escape(job.name)}'.</span>"
            )
            return True
        except (JobAssetError, JobCodecError, JobStoreError, OSError) as error:
            LOG.error(LOG.LOG_SOURCE.FE, f"Failed to update prepared archive: {error}")
            QMessageBox.warning(
                self,
                "Archive Update Failed",
                f"Could not update the prepared archive:\n\n{error}",
            )
            # The archive exists but could not be updated; do not fall through
            # to the ordinary save path, which requires the missing source.
            return True

    def _deferrable_trackers(self) -> dict[TrackerSelection, TrackerRunOutcome]:
        """Trackers this run left un-uploaded that can safely be retried later.

        Anything that reached the tracker -- or might have -- is excluded, so a
        deferred job can never turn into a duplicate upload.
        """
        return {
            tracker: outcome
            for tracker, outcome in self._run_outcomes.items()
            if outcome.is_safe_to_reupload()
        }

    def _offer_deferred_job(self) -> None:
        """Offer to save whatever this run could not upload as a new job.

        This is the escape hatch for a tracker that was down: skip it during
        the run, then keep it for later without re-running the whole wizard.
        The job written here holds *only* the deferred trackers, so it is
        indistinguishable from one saved before any upload was attempted and
        needs no special handling on resume.
        """
        deferrable = self._deferrable_trackers()
        if not deferrable:
            return

        described = ", ".join(
            f"{tracker} ({self._OUTCOME_LABELS.get(outcome, 'not uploaded')})"
            for tracker, outcome in deferrable.items()
        )
        if (
            QMessageBox.question(
                self,
                "Save Remaining Trackers",
                f"{len(deferrable)} tracker(s) were not uploaded:\n\n{described}\n\n"
                "Save them as a job so they can be uploaded later?\n\n"
                "The titles and NFOs from this run are saved with the job, "
                "including any edits you made in the overview, so it will "
                "upload exactly what you saw here.",
            )
            is not QMessageBox.StandardButton.Yes
        ):
            return

        self._save_job(keep_trackers=set(deferrable))

    _OUTCOME_LABELS = {
        TrackerRunOutcome.NOT_ATTEMPTED: "not attempted",
        TrackerRunOutcome.SKIPPED: "skipped",
        TrackerRunOutcome.UPLOAD_FAILED: "upload failed",
    }

    @Slot(object)
    def _on_upload_retry_signal(self, failure: UploadFailure) -> None:
        """Present a retry/skip/cancel choice while the worker waits."""
        action = UploadRetryAction.CANCEL
        # Tell the worker its request was received, so it stops the ack
        # watchdog and waits indefinitely for the user's actual answer.
        GSigs().upload_retry_ack.emit()
        try:
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setWindowTitle(f"Upload failed: {failure.tracker}")
            dialog.setText(
                f"{failure.tracker} failed during {failure.phase.name.lower().replace('_', ' ')}."
            )
            details = (
                f"Attempts: {failure.attempt} "
                f"({failure.automatic_attempts} automatic attempts)\n\n"
                f"{scrub_secrets(failure.message)}"
            )
            if failure.torrent_path:
                details += f"\n\nOutput: {failure.torrent_path.parent}"
            if failure.phase is UploadFailurePhase.DOWNLOAD:
                details += (
                    "\n\nThe upload succeeded. Only downloading the tracker's "
                    "copy of the torrent failed, so the local torrent file was "
                    "kept. Re-uploading would create a duplicate."
                )
            elif failure.phase is UploadFailurePhase.INJECTION:
                details += (
                    "\n\nThe upload succeeded. Only adding the torrent to your "
                    "client failed, so retrying is safe."
                )
            elif failure.server_accepted:
                details += (
                    "\n\nThe tracker may already have accepted this upload. "
                    "Retrying could create a duplicate."
                )
            elif not failure.retryable:
                details += (
                    "\n\nThis does not look like a temporary failure; verify the "
                    "tracker settings before retrying."
                )
            dialog.setInformativeText(details)

            if failure.phase is UploadFailurePhase.DOWNLOAD:
                # The upload itself succeeded; only fetching the tracker's copy
                # of the torrent failed. Re-uploading would duplicate it.
                retry_button = None
                skip_button = dialog.addButton(
                    "Keep upload, continue", QMessageBox.ButtonRole.AcceptRole
                )
                dialog.addButton("Cancel remaining", QMessageBox.ButtonRole.RejectRole)
                dialog.setDefaultButton(skip_button)
            else:
                retry_label = (
                    "Re-upload (may duplicate)" if failure.server_accepted else "Retry"
                )
                retry_button = dialog.addButton(
                    retry_label, QMessageBox.ButtonRole.AcceptRole
                )
                skip_button = dialog.addButton(
                    "Skip tracker", QMessageBox.ButtonRole.DestructiveRole
                )
                dialog.addButton("Cancel remaining", QMessageBox.ButtonRole.RejectRole)
                # Never default to the action that can create a duplicate.
                dialog.setDefaultButton(
                    skip_button if failure.server_accepted else retry_button
                )
            dialog.exec()

            clicked = dialog.clickedButton()
            if retry_button is not None and clicked is retry_button:
                action = UploadRetryAction.RETRY
            elif clicked is skip_button:
                action = UploadRetryAction.SKIP
        except Exception as e:
            # Presenting the dialog failed (e.g. the page was torn down while
            # the prompt was up). Fall back to CANCEL below instead of leaving
            # the exception unhandled.
            LOG.error(
                LOG.LOG_SOURCE.FE,
                f"Failed to present upload retry prompt: {e}\n{traceback.format_exc()}",
            )
        finally:
            # The worker thread is blocked on this response. Releasing it from a
            # finally keeps a dialog failure from hanging the whole run.
            GSigs().upload_retry_response.emit(action)

    def _job_ended(self) -> None:
        self.dupe_worker = None
        # if we just finished processing uploads we can show the open temp button
        if self.process_worker:
            self.open_temp_output_btn.show()
            self.text_widget.ensureCursorVisible()
            if self._run_phase is RunPhase.PREPARE:
                # preparing uploads nothing, so saving is exactly what comes
                # next -- but there is nothing left to prepare a second time
                self.save_job_btn.setDisabled(False)
                self.prepare_job_btn.hide()
            else:
                # uploads have already been attempted, so saving this as a job
                # to run later would only invite duplicate uploads
                self.save_job_btn.hide()
                self.prepare_job_btn.hide()
        else:
            self.save_job_btn.setDisabled(False)
            self.prepare_job_btn.setDisabled(False)
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
            safe_txt = scrub_secrets(txt)
            cursor.insertHtml(safe_txt)
            LOG.info(LOG.LOG_SOURCE.FE, f"Process log: {safe_txt}")
        if not txt:
            cursor.insertHtml("<br />")
        self.text_widget.setTextCursor(cursor)
        self.text_widget.ensureCursorVisible()

    @Slot(str)
    def _on_text_update_replace_last_line(self, txt: str) -> None:
        """Updates last line of text from the start of line"""
        # Same reason `_on_text_update` scrubs before inserting: this channel
        # is reachable from plugins (`UploadReporter.replace_last_line`), and
        # it is what the user actually sees in the log pane -- LOG.info's own
        # sink already scrubs centrally (`nfo_forge_logger.py`), but the
        # inserted HTML does not go through that.
        safe_txt = scrub_secrets(txt)
        cursor = self.text_widget.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(
            QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor
        )
        cursor.removeSelectedText()
        cursor.insertHtml(safe_txt)
        self.text_widget.setTextCursor(cursor)
        self.text_widget.ensureCursorVisible()
        LOG.info(LOG.LOG_SOURCE.FE, f"Process log replace last line: {safe_txt}")

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
            warn_missing=self.config.settings.widgets.prompt_token_editor_warn_on_missing,
            parent=self,
        )
        if prompt.exec() == QDialog.DialogCode.Accepted:
            if (
                prompt.warn_on_missing.isChecked()
                != self.config.settings.widgets.prompt_token_editor_warn_on_missing
            ):
                self.config.settings.widgets.prompt_token_editor_warn_on_missing = (
                    prompt.warn_on_missing.isChecked()
                )
                self.config.save()
            prompt_tokens = prompt.get_results()
        GSigs().prompt_tokens_response.emit(prompt_tokens)

    @Slot(object)
    def _on_overview_signal(
        self, data: dict[TrackerSelection, dict[str, str | None]]
    ) -> None:
        result = data
        prompt = OverviewDialog(data, self)
        if prompt.exec() == QDialog.DialogCode.Accepted:
            result = prompt.get_results()
        GSigs().overview_prompt_response.emit(result)

    def _update_last_used_host(self) -> None:
        start_data = deepcopy(self.config.settings.trackers.last_used_image_host)
        for (
            tracker,
            image_host_data,
        ) in self.context.shared_data.tracker_image_hosts.items():
            img_dest = image_host_data.img_to
            try:
                self.config.settings.trackers.last_used_image_host[tracker] = ImageHost(
                    img_dest
                )
            except ValueError:
                self.config.settings.trackers.last_used_image_host[tracker] = (
                    ImageSource(img_dest)
                )
        if self.config.settings.trackers.last_used_image_host != start_data:
            self.config.save()

    # the label the combo boxes show has to match the one carried in the run
    # data, so both come from the same function
    _image_host_label = staticmethod(image_host_label)

    def _sync_tracker_image_hosts(self) -> None:
        """Mirror the combo box selections onto the shared payload.

        The combo boxes are the UI for this choice, but everything downstream
        (processing, the last-used config entry, saved jobs) reads it from the
        payload so it is never trapped inside the widgets.

        This runs on every `combo_changed` signal, including one fired by a
        row's own combo box while it is still being populated (adding its
        first item transitions a fresh `QComboBox` from no selection to its
        first one, which Qt reports synchronously) -- at that instant the row
        exists in the tree but doesn't have combo data to report yet, so its
        column-1 value comes back as plain (empty) item text rather than the
        combo tuple. Such a row is skipped rather than unpacked; the sync
        `add_tracker_items()` runs once every row has finished being added
        fills it back in.
        """
        selections: dict[TrackerSelection, ImageUploadFromTo] = {}
        for row in self.tracker_process_tree.get_item_values():
            if len(row) != 3:
                continue
            tracker, host_column, _status = row
            if not isinstance(host_column, tuple) or len(host_column) != 2:
                continue
            _combo_text, host_data = host_column
            if not isinstance(host_data, tuple) or len(host_data) != 2:
                continue
            image_host_data, _tracker_and_host = host_data
            if not isinstance(image_host_data, ImageUploadFromTo):
                continue
            selections[TrackerSelection(tracker)] = image_host_data
        self.context.shared_data.tracker_image_hosts.clear()
        self.context.shared_data.tracker_image_hosts.update(selections)

    def add_tracker_items(self) -> None:
        # sort the trackers in the users desired order before displaying them
        if self.context.shared_data.selected_trackers:
            # snapshot before any rows are built: adding rows fires
            # `combo_changed`, which re-syncs (and would otherwise clear) the
            # selections a loaded job restored into the payload
            restored_hosts = dict(self.context.shared_data.tracker_image_hosts)
            upload_type = ImageSource.IMAGES
            enabled_img_hosts: dict[
                ImageHost | ImageSource, bool | ImagePayloadBase | list[ImageUploadData]
            ] = {ImageHost.DISABLED: False}

            # if url data is detected add that to the potential options
            if self.context.shared_data.url_data:
                upload_type = ImageSource.URLS
                enabled_img_hosts = enabled_img_hosts | {
                    upload_type: self.context.shared_data.url_data
                }

            # if we have any image data, filter all image hosts that are enabled and have all required values filled
            if (
                self.context.shared_data.loaded_images
                or self.context.shared_data.url_data
            ):
                enabled_img_hosts = enabled_img_hosts | {
                    key: value
                    for key, value in self.config.settings.image_hosts.by_selection().items()
                    if value.enabled
                    and all(
                        getattr(value, field.name)
                        for field in fields(value)
                        if field.name != "enabled"
                    )
                }
                # a plugin-provided image host has no `ImagePayloadBase` entry in
                # `by_selection()` (it manages its own config); its availability
                # here comes entirely from the Settings > Plugins selection instead
                if self._plugin_image_host_available():
                    enabled_img_hosts = enabled_img_hosts | {ImageHost.PLUGIN: True}

            # A host this job already uploaded to can be served from the stored
            # URLs alone -- no local screenshots, and no credentials, since
            # nothing is sent. That is the only option a source-less archive
            # has, so without this an archive whose `images/` is gone offered
            # nothing but `Disabled` and silently uploaded to nobody.
            enabled_img_hosts = enabled_img_hosts | {
                host: True
                for host in self.context.shared_data.uploaded_images_by_host
                if isinstance(host, ImageHost)
                and host is not ImageHost.DISABLED
                and host not in enabled_img_hosts
            }

            ordered_trackers = [
                x
                for x in sorted(
                    self.context.shared_data.selected_trackers,
                    key=lambda tracker: self.config.settings.trackers.order.index(
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
                                    self._image_host_label(upload_type, img_host),
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
                if not combo_box:
                    continue

                # a restored job knows exactly which destination was chosen, so
                # match it directly; otherwise fall back to the remembered
                # preference, which only has the destination to go on
                restored_host = restored_hosts.get(tracker)
                if restored_host:
                    restored_idx = combo_box.findText(
                        self._image_host_label(upload_type, restored_host.img_to)
                    )
                    if restored_idx != -1:
                        combo_box.setCurrentIndex(restored_idx)
                        continue

                last_used_host = self.config.settings.trackers.last_used_image_host.get(
                    tracker
                )
                if last_used_host:
                    get_last = combo_box.findText(
                        str(last_used_host), flags=Qt.MatchFlag.MatchContains
                    )
                    if get_last != -1:
                        combo_box.setCurrentIndex(get_last)

        # Outside the branch on purpose: the rows are the run, so with no
        # tracker to build a row for there is no run, and the payload has to
        # say so. A restored job can arrive carrying image hosts for trackers
        # it is only holding state for -- an unconfirmed upload keeps its
        # entry -- and leaving those in place let a run with no rows at all
        # still hand the backend a tracker to upload to.
        self._sync_tracker_image_hosts()

    def _plugin_image_host_available(self) -> bool:
        """Whether a loaded plugin currently provides image host uploads.

        There is no separate enable/disable toggle for this in Settings ->
        Image Hosts: the Settings -> Plugins selection is the single source
        of truth, same as every other plugin capability.
        """
        if not self.config.settings.general.enable_plugins:
            return False
        plugin_id = self.config.settings.plugins.image_host_uploader
        if not plugin_id:
            return False
        record = self.config.plugin_manager.get(plugin_id)
        return bool(record and record.definition.image_host_uploader is not None)

    @Slot(QComboBox, int)
    def _tree_combo_changed(self, _combo: QComboBox, _idx: int) -> None:
        self.save_config = True
        self._sync_tracker_image_hosts()

    def _gather_tracker_data(self, detected_input: Path) -> dict[str, Any] | None:
        process_dir = self.context.media_input.working_dir
        if not process_dir:
            raise ValueError("Failed to detect MediaInputPayload.working_dir")

        tracker_data = build_tracker_data(
            working_dir=process_dir,
            input_path=detected_input,
            tracker_image_hosts=self.context.shared_data.tracker_image_hosts,
            input_is_directory=self.context.media_input.input_is_directory(),
        )

        # the prompt is the one part that needs a user, so it stays here rather
        # than in the shared builder the queue also calls
        if self.processing_mode is UploadProcessMode.UPLOAD:
            for tracker, entry in tracker_data.items():
                chosen = self._confirm_torrent_output(tracker, entry["path"])
                if chosen is None:
                    return None
                entry["path"] = chosen

        if not tracker_data:
            tracker_paths_error_msg = "Failed to generate tracker data"
            LOG.error(LOG.LOG_SOURCE.FE, tracker_paths_error_msg)
            raise ProcessError(tracker_paths_error_msg)

        return tracker_data

    def _confirm_torrent_output(self, tracker: str, torrent_out: Path) -> Path | None:
        """Settle where a tracker's torrent goes when one is already there.

        Returns the path to use, or None when the user backed out entirely.
        """
        if not torrent_out.exists():
            return torrent_out
        if (
            QMessageBox.question(
                self,
                "Overwrite?",
                f"\n\nTracker: {tracker}\n\nFile: {torrent_out}\n\nFile already "
                "exists, would you like to overwrite?",
            )
            is not QMessageBox.StandardButton.No
        ):
            return torrent_out

        new_torrent_out, _ = QFileDialog.getSaveFileName(
            parent=self,
            caption="Select Save Output",
            filter="*.torrent",
            dir=str(torrent_out.parent),
        )
        return Path(new_torrent_out) if new_torrent_out else None

    def get_theme_colors(self) -> str:
        app = cast(QApplication | None, QApplication.instance())
        if app:
            color_scheme = app.styleHints().colorScheme()
            scheme = "dark" if color_scheme == Qt.ColorScheme.Dark else "light"
            return self.THEMES[scheme]["box_color"]
        return "#e6e6e6"

    @Slot()
    def _open_temp_output(self) -> None:
        if (
            self.context.media_input.working_dir
            and self.context.media_input.working_dir.exists()
        ):
            open_explorer(self.context.media_input.working_dir)

    def initializePage(self) -> None:
        self.source_less_banner.setVisible(self._source_less_run())
        self.add_tracker_items()
