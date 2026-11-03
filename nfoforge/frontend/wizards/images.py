from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal, SignalInstance, Slot
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nfoforge.backend.images import ImagesBackEnd
from nfoforge.backend.utils.images import (
    extract_images_from_str,
)
from nfoforge.config.config import ConfigManager
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.core.screenshots.plan import (
    CropSource,
    ScreenshotPlan,
    generate_screenshots,
    plan_screenshots,
    resolve_crop,
    screenshot_mode,
)
from nfoforge.enums.screen_shot_mode import ScreenShotMode
from nfoforge.exceptions.utils import get_full_traceback
from nfoforge.frontend.custom_widgets.custom_splitter import CustomSplitter
from nfoforge.frontend.custom_widgets.dnd_factory import (
    DNDThumbnailListWidget,
    DNDToolButton,
)
from nfoforge.frontend.global_signals import GSigs
from nfoforge.frontend.stacked_windows.cropping import CropWidgetDialog
from nfoforge.frontend.utils import build_v_line
from nfoforge.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from nfoforge.frontend.windows.image_viewer import ImageViewer
from nfoforge.frontend.wizards.wizard_base_page import BaseWizardPage
from nfoforge.logger.nfo_forge_logger import LOG
from nfoforge.payloads.script import ScriptValues

if TYPE_CHECKING:
    from nfoforge.frontend.windows.main_window import MainWindow


class QueuedWorker(QThread):
    """Runs one `ScreenshotPlan` off the UI thread."""

    job_finished = Signal(int)
    job_failed = Signal(str)

    def __init__(
        self,
        backend: ImagesBackEnd,
        plan: ScreenshotPlan,
        progress_signal: SignalInstance,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.backend = backend
        self.plan = plan
        self.progress_signal = progress_signal

    def run(self) -> None:
        try:
            self.job_finished.emit(
                generate_screenshots(self.plan, self.backend, self.progress_signal)
            )
        except Exception as e:
            LOG.error(LOG.LOG_SOURCE.FE, get_full_traceback(e))
            self.job_failed.emit(f"Error: Please check logs for more details ({e})")


class ImagesPage(BaseWizardPage):
    progress_signal_generation = Signal(str, float)

    def __init__(
        self,
        config: ConfigManager,
        context: ProcessingContext,
        parent: "MainWindow",
    ) -> None:
        super().__init__(config, context, parent)
        self.setObjectName("imagesPage")
        self.setTitle("""<h4>Images</h4><span style="font-size: 9pt; font-weight: normal;">
                        Built-in image generation produces 
                        <span style="font-weight: 500;">high-quality optimized PNG</span> images. This is a 
                        <span style="font-weight: 500; text-decoration: underline;">requirement</span> 
                        for some trackers. You can open existing images or URLs, but you should 
                        ensure that user-provided images and URLs meet the tracker's specifications.</span>""")
        self.setCommitPage(True)

        self.main_window = parent

        self.config = config
        self.backend = ImagesBackEnd()
        self.loading_complete = True

        self.queued_worker: QueuedWorker | None = None
        self.progress_signal_generation.connect(self._progress_callback)

        self.image_viewer: ImageViewer | None = None
        self.image_dir: Path | None = None
        self.script_values: ScriptValues | None = None

        # we need to keep track of the type of images that are dropped/generated
        # to update SharedPayload.is_comparison_images
        self.is_comparison_images = False

        self.generate_images = QPushButton("Generate", self)
        self.generate_images.setToolTip("Generates images from media file(s).")
        self.generate_images.clicked.connect(self._generate_images)

        self.progress_bar = QProgressBar(self)

        open_images_btn = DNDToolButton(self)
        QTAThemeSwap().register(
            open_images_btn, "ph.file-arrow-down-light", icon_size=QSize(20, 20)
        )
        open_images_btn.setToolTip("Use existing generated images (.png, .jpg, .jpeg).")
        open_images_btn.clicked.connect(self._open_images)

        paste_urls = DNDToolButton(self)
        QTAThemeSwap().register(
            paste_urls, "ph.clipboard-light", icon_size=QSize(20, 20)
        )
        paste_urls.setToolTip("Paste image URLs from clipboard.")
        paste_urls.clicked.connect(self._handle_url_paste)

        image_gen_control = QGroupBox("Control")
        progress_layout = QHBoxLayout(image_gen_control)
        progress_layout.addWidget(self.generate_images)
        progress_layout.addWidget(self.progress_bar, stretch=10)
        progress_layout.addWidget(build_v_line((1, 0, 1, 0)))
        progress_layout.addWidget(open_images_btn)
        progress_layout.addWidget(build_v_line((1, 0, 1, 0)))
        progress_layout.addWidget(paste_urls)

        self.text_box = QPlainTextEdit(self, readOnly=True)
        self.text_box.setFrameShape(QFrame.Shape.Box)
        self.text_box.setFrameShadow(QFrame.Shadow.Sunken)

        image_gen_log_box = QGroupBox("Log")
        image_gen_log_box_layout = QVBoxLayout(image_gen_log_box)
        image_gen_log_box_layout.addWidget(self.text_box)

        self.thumbnail_listbox = DNDThumbnailListWidget(self)
        self.thumbnail_listbox.setFrameShape(QFrame.Shape.Box)
        self.thumbnail_listbox.setFrameShadow(QFrame.Shadow.Sunken)
        self.thumbnail_listbox.enable_mono_text()

        image_gen_thumbnail_box = QGroupBox("Images")
        image_gen_thumbnail_box_layout = QVBoxLayout(image_gen_thumbnail_box)
        image_gen_thumbnail_box_layout.addWidget(self.thumbnail_listbox)

        # make widgets DnD-able
        for dnd_widget in (open_images_btn, self.thumbnail_listbox):
            dnd_widget.set_extensions((".png", ".jpg", ".jpeg"))
            dnd_widget.set_accept_dir(True)
            dnd_widget.set_accept_text(True)
            dnd_widget.dropped.connect(self._handle_image_drop)
            dnd_widget.text_dropped.connect(self._handle_image_text_drop)

        # use a custom vertical splitter so users can resize the Log and Images panes
        splitter = CustomSplitter(Qt.Orientation.Vertical, self)
        splitter.setChildrenCollapsible(True)
        splitter.addWidget(image_gen_log_box)
        splitter.addWidget(image_gen_thumbnail_box)

        main_layout = QVBoxLayout()
        main_layout.addWidget(image_gen_control)
        main_layout.addWidget(splitter, stretch=1)
        main_layout_widget = QWidget()
        main_layout_widget.setLayout(main_layout)

        self.main_scroll_area = QScrollArea(self, widgetResizable=True)
        self.main_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.main_scroll_area.setWidget(main_layout_widget)

        final_layout = QVBoxLayout(self)
        final_layout.setContentsMargins(0, 0, 0, 0)
        final_layout.addWidget(self.main_scroll_area)

        self.setLayout(final_layout)

    def initializePage(self) -> None:
        if not self.context.media_input.has_basic_data():
            raise RuntimeError("Missing required data from media input")

    def isComplete(self) -> bool:
        """Overrides isComplete method to control the next button"""
        return self.loading_complete

    def validatePage(self) -> bool:
        """Overrides validatePage method to run additional tasks"""
        if (
            not self.context.shared_data.loaded_images
            and not self.context.shared_data.url_data
        ):
            if (
                QMessageBox.question(
                    self,
                    "Continue",
                    "Missing URL data or images, would you like continue without including screenshots?",
                )
                is QMessageBox.StandardButton.No
            ):
                return False

        # log used data
        if self.context.shared_data.loaded_images:
            img_path_data = "\n".join(
                str(p) for p in self.context.shared_data.loaded_images
            )
            LOG.info(
                LOG.LOG_SOURCE.FE,
                f"#### IMG Path Data ####\n{img_path_data}\n#### IMG Path Data ####",
            )
        if self.context.shared_data.url_data:
            img_url_data = "\n".join(
                str(url_d) for url_d in self.context.shared_data.url_data
            )
            LOG.info(
                LOG.LOG_SOURCE.FE,
                f"#### IMG URL Data ####\n{img_url_data}\n#### IMG URL Data ####",
            )

        super().validatePage()
        self.context.shared_data.is_comparison_images = self.is_comparison_images
        return True

    @Slot(str, float)
    def _progress_callback(self, line: str, progress: float) -> None:
        self._update_text_box(line)
        self.progress_bar.setValue(int(progress))

    def _update_text_box(self, txt: str) -> None:
        self.text_box.appendPlainText(txt)
        self.text_box.ensureCursorVisible()

    @Slot()
    def _generate_images(self) -> None:
        try:
            self.context.media_input.require_existing_media_paths(
                include_comparison=True
            )
        except (FileNotFoundError, RuntimeError) as error:
            QMessageBox.critical(
                self,
                "Media Files Unavailable",
                f"Image generation cannot start because its input paths are no "
                f"longer valid:\n\n{error}",
            )
            return

        crop_source, script_values = resolve_crop(self.context, self.config.settings)
        if crop_source is CropSource.SCRIPT:
            self._execute_image_generation(script_values=script_values)
            return

        if crop_source is CropSource.MANUAL:
            dlg = CropWidgetDialog(self)
            # if we have the script pre-load it to work from
            comp_pair = self.context.media_input.comparison_pair
            if comp_pair and comp_pair.script:
                dlg.load_script(comp_pair.script)
            script_values = dlg.exec_crop()
            if script_values:
                self._execute_image_generation(script_values=script_values)
                return

        # nothing to crop (or the crop dialog was cancelled): generate as-is
        self._execute_image_generation()

    @Slot()
    def _execute_image_generation(
        self,
        script_values: ScriptValues | None = None,
        re_sync: int = 0,
    ) -> None:
        if script_values:
            self.script_values = script_values

        if self.queued_worker is not None and self.queued_worker.isRunning():
            return

        try:
            plan = plan_screenshots(
                self.context,
                self.config.settings,
                script_values=script_values,
                re_sync=re_sync,
            )
        except (FileNotFoundError, KeyError, RuntimeError) as error:
            QMessageBox.critical(
                self,
                "Image Generation Setup Failed",
                f"Could not prepare image generation:\n\n{error}",
            )
            return
        self.image_dir = plan.output_directory

        GSigs().main_window_set_disabled.emit(True)
        self.text_box.clear()
        self.thumbnail_listbox.clear()
        self._disable_generate_images_button()
        self._update_loading_state(False)
        self._update_text_box(f"Starting image generation (Mode: {plan.mode}).")

        try:
            self._start_queued_worker(plan)
        except Exception as error:
            self._complete_loading()
            QMessageBox.critical(
                self,
                "Image Generation Setup Failed",
                f"Could not start image generation:\n\n{error}",
            )

    def _disable_generate_images_button(self) -> None:
        self.generate_images.setEnabled(False)

    def _update_loading_state(self, state: bool) -> None:
        self.loading_complete = state
        self.completeChanged.emit()

    def _start_queued_worker(self, plan: ScreenshotPlan) -> None:
        if self.queued_worker is not None:
            # Safe: the only caller, `_execute_image_generation`, already
            # returned early if the previous worker's `isRunning()` was True,
            # and nothing between that check and here re-enters the event
            # loop, so the previous worker is guaranteed finished.
            self.queued_worker.deleteLater()
        self.queued_worker = QueuedWorker(
            backend=self.backend,
            plan=plan,
            progress_signal=self.progress_signal_generation,
            parent=self,
        )
        self.queued_worker.job_finished.connect(self._generate_finished)
        self.queued_worker.job_failed.connect(self._generate_failed)
        self.queued_worker.start()

    @Slot(int)
    def _generate_finished(self, code: int) -> None:
        if code != 0:
            QMessageBox.warning(
                self,
                "Error",
                f"Failed to generate images, check logs for more information ({code})",
            )
            self._complete_loading()
            return

        if self.image_viewer is not None:
            self.image_viewer.deleteLater()
            self.image_viewer = None

        # Opening the viewer is what re-enables the main window on this path,
        # so nothing else will if it fails: `_execute_image_generation`
        # disabled the window before starting the worker, and it would stay
        # disabled for the rest of the session -- which is indistinguishable
        # from a freeze. The viewer raises for real reasons (no frames
        # produced, an empty comparison set), so it cannot be assumed to open.
        try:
            ss_mode = screenshot_mode(self.context, self.config.settings)
            if not self.image_dir:
                raise RuntimeError("Failed to determine image_dir")
            self.image_viewer = ImageViewer(
                image_base_dir=self.image_dir,
                comparison_mode=ss_mode,
                min_required_selected_screens=self.config.settings.screenshots.min_required_selected,
                max_required_selected_screens=self.config.settings.screenshots.max_required_selected,
                parent=self,
            )
            self.image_viewer.show()
        except Exception as error:
            if self.image_viewer is not None:
                self.image_viewer.deleteLater()
                self.image_viewer = None
            LOG.error(LOG.LOG_SOURCE.FE, get_full_traceback(error))
            self._complete_loading()
            QMessageBox.critical(
                self,
                "Error",
                "Images were generated but the viewer could not be opened, "
                f"check logs for more information ({error})",
            )
            return

        GSigs().main_window_set_disabled.emit(False)
        self.image_viewer.exit_viewer.connect(self._on_exit_viewer)
        self.image_viewer.re_sync_images.connect(self._re_sync)

    @Slot(list)
    def _on_exit_viewer(self, images: list[Path]) -> None:
        # A bound method so Qt can disconnect it by receiver lifetime; a
        # lambda cannot be auto-disconnected and kept the viewer alive.
        self._load_images(images, True)

    @Slot(str)
    def _generate_failed(self, e: str) -> None:
        self._complete_loading()
        LOG.debug(LOG.LOG_SOURCE.FE, e)
        QMessageBox.critical(self, "Error", e)

    @Slot()
    def _handle_url_paste(self) -> None:
        clipboard = QApplication.clipboard().text()
        if clipboard:
            self._handle_image_text_drop(clipboard)

    @Slot(str)
    def _handle_image_text_drop(self, urls: str) -> None:
        self.thumbnail_listbox.clear()
        _, _, img_objs = extract_images_from_str(urls)
        if img_objs:
            self._update_text_box("Successfully parsed images!")
            self.thumbnail_listbox.addItems([str(x) for x in img_objs])
        else:
            self._update_text_box("No image URLs detected.")
        self.context.shared_data.url_data = img_objs
        self.is_comparison_images = self._ask_comparison()
        self._complete_loading()

    @Slot()
    def _open_images(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            caption="Open Image File(s)", filter="*.png *.jpg *.jpeg"
        )
        if files:
            self._load_images([Path(x) for x in files], False)

    @Slot(list)
    def _handle_image_drop(self, image_s: list[Path]) -> None:
        if not image_s:
            return

        images_only = [img for img in image_s if img.is_file()] + [
            sub_img for img in image_s if img.is_dir() for sub_img in img.glob("*.png")
        ]

        self._load_images(images_only, False)

    @Slot(list, bool)
    def _load_images(self, images: list[Path], generated: bool) -> None:
        self.generate_images.setEnabled(True)
        self.thumbnail_listbox.clear()
        if images:
            for img in images:
                self.thumbnail_listbox.add_thumbnail(img)
            self.context.shared_data.loaded_images = images
            self.context.shared_data.generated_images = generated

            # if generated we need to check the ss_mode to determine if these are comp images
            if (
                generated
                and self.config.settings.screenshots.mode is ScreenShotMode.BASIC_SS_GEN
            ):
                self.is_comparison_images = False
            elif (
                generated
                and self.config.settings.screenshots.mode
                is not ScreenShotMode.BASIC_SS_GEN
            ):
                self.is_comparison_images = True
            # if not generated we need to ask the user the type of images
            elif not generated:
                self.is_comparison_images = self._ask_comparison()

        self._complete_loading()

    def _ask_comparison(self) -> bool:
        if (
            QMessageBox.question(
                self,
                "Image Type",
                "Are the dropped images comparison images?",
            )
            is QMessageBox.StandardButton.Yes
        ):
            return True
        return False

    @Slot(int)
    def _re_sync(self, offset: int) -> None:
        self._execute_image_generation(
            script_values=self.script_values,
            re_sync=offset,
        )

    def _complete_loading(self) -> None:
        GSigs().main_window_set_disabled.emit(False)
        self.generate_images.setEnabled(True)
        self._update_loading_state(True)
        self._reset_vars()

    def _reset_vars(self) -> None:
        self.image_dir = None
        self.script_values = None
