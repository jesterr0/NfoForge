from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING

from pymediainfo import MediaInfo
from PySide6.QtCore import QSize, QThread, Signal, SignalInstance, Slot
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

from src.backend.images import ImagesBackEnd
from src.backend.utils.images import (
    compare_resolutions,
    determine_sub_size,
    extract_images_from_str,
)
from src.backend.utils.script_parser import ScriptParser
from src.config.config import Config
from src.context.processing_context import ProcessingContext
from src.enums.cropping import Cropping
from src.enums.image_plugin import ImagePlugin
from src.enums.indexer import Indexer
from src.enums.screen_shot_mode import ScreenShotMode
from src.enums.subtitles import SubtitleAlignment
from src.exceptions.utils import get_full_traceback
from src.frontend.custom_widgets.dnd_factory import (
    DNDThumbnailListWidget,
    DNDToolButton,
)
from src.frontend.global_signals import GSigs
from src.frontend.stacked_windows.cropping import CropWidgetDialog
from src.frontend.utils import build_v_line
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from src.frontend.windows.image_viewer import ImageViewer
from src.frontend.wizards.media_input import MediaInput
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.logger.nfo_forge_logger import LOG
from src.packages.custom_types import SubNames
from src.payloads.script import ScriptValues

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow

# TODO: make log bigger, make window scrollable, on finish scroll to the bottom of the page or to the image widget
# TODO: clean up all the type hint errors/warnings.


class QueuedWorker(QThread):
    job_finished = Signal(int)
    job_failed = Signal(str)

    def __init__(
        self,
        backend: ImagesBackEnd,
        ss_mode: ScreenShotMode,
        media_file: Path,
        media_file_mi_obj: MediaInfo,
        output_directory: Path,
        total_images: int,
        trim: tuple[int, int],
        subtitle_color: str,
        subtitle_outline_color: str,
        sub_names: SubNames | None,
        sub_size: int,
        subtitle_alignment: SubtitleAlignment,
        crop_mode: Cropping,
        script_values: ScriptValues | None,
        re_sync: int,
        indexer: Indexer | None,
        image_plugin: ImagePlugin | None,
        ffmpeg_path: Path,
        frame_forge_path: Path | None,
        progress_signal: SignalInstance,
        source_file: Path | None = None,
        source_file_mi_obj: MediaInfo | None = None,
        parent=None,
    ) -> None:
        """
        Generate images and emit progress signals.

        Parameters:
            backend (ImagesBackEnd): Backend class to handle image generation.
            ss_mode (ScreenShotMode): Selected ScreenShotMode.
            media_file (Path): The input file path.
            media_file_mi_obj (MediaInfo): MediaInfo object of the input file.
            output_directory (Path): The output directory path.
            total_images (int): The total number of images to generate.
            trim (tuple[int, int]): The percentage of the file to trim from start and end.
            subtitle_color (str): Hex color.
            subtitle_outline_color (str): Hex color.
            sub_names (Optional[SubNames]): Subtitle names.
            sub_size (int): Subtitle size.
            subtitle_alignment (SubtitleAlignment): Subtitle alignment.
            crop_mode (Cropping): Crop mode.
            script_values (Optional[ScriptValues]): Script values.
            re_sync (int): Re_sync value.
            indexer (Optional[Indexer]): Indexer used for FrameForge.
            image_plugin (Optional[ImagePlugin]): Plugin used for image generation in FrameForge.
            ffmpeg_path (Path): Path to FFMPEG executable.
            frame_forge_path (Path): Path to FFMPEG executable.
            progress_signal (SignalInstance[str, float]): The signal used to emit progress updates.
            source_file (Optional[Path]): The input file path for the source.
            source_file_mi_obj (Optional[Path]): MediaInfo object of the input file.
        """
        super().__init__(parent=parent)
        self.backend = backend
        self.ss_mode = ss_mode
        self.media_file = media_file
        self.media_file_mi_obj = media_file_mi_obj
        self.output_directory = output_directory
        self.total_images = total_images
        self.trim = trim
        self.subtitle_color = subtitle_color
        self.subtitle_outline_color = subtitle_outline_color
        self.sub_names = sub_names
        self.sub_size = sub_size
        self.subtitle_alignment = subtitle_alignment
        self.crop_mode = crop_mode
        self.crop_values = script_values.crop_values if script_values else None
        self.advanced_resize = script_values.advanced_resize if script_values else None
        self.re_sync = re_sync
        self.indexer = indexer
        self.image_plugin = image_plugin
        self.ffmpeg_path = ffmpeg_path
        self.frame_forge_path = frame_forge_path
        self.progress_signal = progress_signal
        self.source_file = source_file
        self.source_file_mi_obj = source_file_mi_obj

    def run(self) -> None:
        try:
            if self.ss_mode == ScreenShotMode.BASIC_SS_GEN:
                self._basic_generation()
            elif self.ss_mode == ScreenShotMode.SIMPLE_SS_COMP:
                if not self.source_file:
                    self.job_failed.emit("Must have 'source_input' for this profile")
                    return
                self._comparison_generation()
            elif self.ss_mode == ScreenShotMode.ADV_SS_COMP:
                if not self.source_file:
                    self.job_failed.emit("Must have 'source_input' for this profile")
                    return
                self._adv_comparison_generation()
        except Exception as e:
            LOG.error(LOG.LOG_SOURCE.FE, get_full_traceback(e))
            self.job_failed.emit(f"Error: Please check logs for more details ({e})")

    def _basic_generation(self) -> None:
        job = self.backend.basic_image_generation(
            self.media_file,
            self.output_directory,
            self.media_file_mi_obj,
            self.total_images,
            self.trim,
            self.ffmpeg_path,
            self.progress_signal,
        )
        self.job_finished.emit(job)

    def _comparison_generation(self) -> None:
        if not self.source_file or not self.source_file_mi_obj:
            raise RuntimeError(
                "Failed to execute comparison image generation: source_file and/or source_file_mi_obj is missing"
            )
        job = self.backend.comparison_image_generation(
            self.source_file,
            self.source_file_mi_obj,
            self.media_file,
            self.media_file_mi_obj,
            self.output_directory,
            self.total_images,
            self.trim,
            self.subtitle_color,
            self.subtitle_outline_color,
            self.sub_names,
            self.sub_size,
            self.crop_mode,
            self.crop_values,
            self.ffmpeg_path,
            self.progress_signal,
            self.re_sync,
        )
        self.job_finished.emit(job)

    def _adv_comparison_generation(self) -> None:
        if (
            not self.source_file
            or not self.source_file_mi_obj
            or not self.indexer
            or not self.image_plugin
            or not self.frame_forge_path
        ):
            raise RuntimeError(
                "Failed to execute comparison image generation: one or all of "
                f"({self.source_file=}, {self.source_file_mi_obj=}, {self.indexer=}, "
                f"{self.image_plugin=}, {self.frame_forge_path=}) is missing"
            )
        job = self.backend.frame_forge_image_generation(
            self.source_file,
            self.source_file_mi_obj,
            self.media_file,
            self.media_file_mi_obj,
            self.output_directory,
            self.total_images,
            self.trim,
            self.subtitle_color,
            self.subtitle_outline_color,
            self.sub_names,
            self.sub_size,
            self.subtitle_alignment,
            self.crop_mode,
            self.crop_values,
            self.advanced_resize,
            self.re_sync,
            self.indexer,
            self.image_plugin,
            self.frame_forge_path,
            self.ffmpeg_path,
            self.progress_signal,
        )
        self.job_finished.emit(job)


class ImagesPage(BaseWizardPage):
    progress_signal_generation = Signal(str, float)

    def __init__(
        self,
        config: Config,
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
        self.source_file: Path | None = None
        self.media_file: Path | None = None
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

        self.text_box = QPlainTextEdit(self)
        self.text_box.setFrameShape(QFrame.Shape.Box)
        self.text_box.setFrameShadow(QFrame.Shadow.Sunken)
        self.text_box.setReadOnly(True)

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

        main_layout = QVBoxLayout()
        main_layout.addWidget(image_gen_control)
        main_layout.addWidget(image_gen_log_box, stretch=1)
        main_layout.addWidget(image_gen_thumbnail_box, stretch=3)
        main_layout_widget = QWidget()
        main_layout_widget.setLayout(main_layout)

        self.main_scroll_area = QScrollArea(self)
        self.main_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.main_scroll_area.setWidgetResizable(True)
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
                (str(p) for p in self.context.shared_data.loaded_images)
            )
            LOG.info(
                LOG.LOG_SOURCE.FE,
                f"#### IMG Path Data ####\n{img_path_data}\n#### IMG Path Data ####",
            )
        if self.context.shared_data.url_data:
            img_url_data = "\n".join(
                (str(url_d) for url_d in self.context.shared_data.url_data)
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
        ss_mode = self.config.cfg_payload.ss_mode
        crop_mode = self.config.cfg_payload.crop_mode

        # if ScreenShotMode is not basic we can run comparison logic
        if ss_mode is not ScreenShotMode.BASIC_SS_GEN:
            # if the user didn't provide a comparison pair we'll just generated via basic
            comp_pair = self.context.media_input.comparison_pair
            if not comp_pair:
                self._execute_image_generation()
                return

            if not self._compare_resolutions():
                # if manual we will prompt the crop dialog widget
                if crop_mode is Cropping.MANUAL:
                    dlg = CropWidgetDialog(self)
                    # if we have the script pre-load it even if using manual
                    if comp_pair.script:
                        dlg.load_script(comp_pair.script)
                    script_values = dlg.exec_crop()
                    if script_values:
                        self._execute_image_generation(script_values=script_values)
                        return
                # if auto and there is a script already we can apply the values if they are valid
                elif crop_mode is Cropping.AUTO and comp_pair.script:
                    parse_script = ScriptParser(comp_pair.script.read_text()).get_data()
                    if not parse_script.all_zeros():
                        self._execute_image_generation(
                            script_values=ScriptParser(
                                comp_pair.script.read_text()
                            ).get_data()
                        )
                        return

        # if comparison logic was not needed just fall back to regular generation
        # allowing it to detect the correct flow
        self._execute_image_generation()

    def _compare_resolutions(self) -> bool:
        comp_pair = self.context.media_input.comparison_pair
        mi_list = self.context.media_input.file_list_mediainfo
        if not comp_pair or not mi_list:
            raise AttributeError("Failed to get data from comparison pair")
        if not compare_resolutions(
            mi_list[comp_pair.source],
            mi_list[comp_pair.media],
        ):
            return False
        return True

    def _read_advanced_script(self, script: PathLike[str]) -> str:
        with open(script, "r", encoding="utf-8") as read_script:
            return read_script.read()

    @Slot()
    def _execute_image_generation(
        self,
        script_values: ScriptValues | None = None,
        re_sync: int = 0,
    ) -> None:
        crop_mode = self.config.cfg_payload.crop_mode
        if script_values:
            self.script_values = script_values

        if self.queued_worker is not None and self.queued_worker.isRunning():
            return

        GSigs().main_window_set_disabled.emit(True)
        self.text_box.clear()
        self.thumbnail_listbox.clear()
        self._disable_generate_images_button()
        self._update_loading_state(False)

        ss_mode, source_file_mi_obj, media_file_mi_obj, comparison_subs = (
            self._generate_job_args()
        )
        self._update_text_box(f"Starting image generation (Mode: {ss_mode}).")

        self._set_image_directory()

        subtitle_color = self.config.cfg_payload.subtitle_color
        subtitle_outline_color = self.config.cfg_payload.subtitle_outline_color
        sub_names = self._get_sub_names(comparison_subs)
        sub_size = determine_sub_size(
            media_file_mi_obj.video_tracks[0].height,
            self.config.cfg_payload.sub_size_height_720,
            self.config.cfg_payload.sub_size_height_1080,
            self.config.cfg_payload.sub_size_height_2160,
        )
        subtitle_alignment = self.config.cfg_payload.subtitle_alignment

        self._start_queued_worker(
            ss_mode,
            media_file_mi_obj,
            source_file_mi_obj,
            subtitle_color,
            subtitle_outline_color,
            sub_names,
            sub_size,
            subtitle_alignment,
            crop_mode,
            script_values,
            re_sync,
        )

    def _disable_generate_images_button(self) -> None:
        self.generate_images.setEnabled(False)

    def _update_loading_state(self, state: bool) -> None:
        self.loading_complete = state
        self.completeChanged.emit()

    def _generate_job_args(self) -> tuple:
        """Determine image generation args."""
        file_list = self.context.media_input.file_list
        mi_file_list = self.context.media_input.file_list_mediainfo
        if not file_list or not mi_file_list:
            raise AttributeError(
                "No files detected in file_list or file_list_mediainfo"
            )

        comp_pair = self.context.media_input.comparison_pair
        # no comparison generation
        if not comp_pair:
            # access index 0 since no comparison pair
            self.media_file = file_list[0]
            return (
                ScreenShotMode.BASIC_SS_GEN,
                None,
                mi_file_list[self.media_file],
                False,
            )

        # comparison generation
        else:
            self.source_file = comp_pair.source
            self.media_file = comp_pair.media
            ss_mode = (
                ScreenShotMode.SIMPLE_SS_COMP
                if self.config.cfg_payload.ss_mode is not ScreenShotMode.ADV_SS_COMP
                else ScreenShotMode.ADV_SS_COMP
            )
            return (
                ss_mode,
                mi_file_list[self.source_file],
                mi_file_list[self.media_file],
                self.config.cfg_payload.comparison_subtitles,
            )

    def _set_image_directory(self) -> None:
        if not self.context.media_input.working_dir:
            raise FileNotFoundError(
                "Failed to locate path to 'working directory for media'"
            )
        self.image_dir = self.context.media_input.working_dir / "images"

    def _get_sub_names(self, comparison_subs) -> SubNames | None:
        if comparison_subs:
            return SubNames(
                self.config.cfg_payload.comparison_subtitle_source_name,
                self.config.cfg_payload.comparison_subtitle_encode_name,
            )
        return None

    def _start_queued_worker(
        self,
        ss_mode,
        media_file_mi_obj,
        source_file_mi_obj,
        subtitle_color,
        subtitle_outline_color,
        sub_names,
        sub_size,
        subtitle_alignment,
        crop_mode: Cropping,
        script_values: ScriptValues | None,
        re_sync,
    ) -> None:
        if (
            not self.media_file
            or not self.image_dir
            or not self.config.cfg_payload.ffmpeg
        ):
            raise RuntimeError(
                "Failed to execute image worker, missing one or more required inputs "
                f"({self.media_file=}, {self.image_dir=}, {self.config.cfg_payload.ffmpeg=})"
            )
        self.queued_worker = QueuedWorker(
            backend=self.backend,
            ss_mode=ss_mode,
            media_file=self.media_file,
            media_file_mi_obj=media_file_mi_obj,
            output_directory=self.image_dir,
            total_images=self.config.cfg_payload.screen_shot_count,
            trim=(self.config.cfg_payload.trim_start, self.config.cfg_payload.trim_end),
            ffmpeg_path=self.config.cfg_payload.ffmpeg,
            frame_forge_path=self.config.cfg_payload.frame_forge,
            progress_signal=self.progress_signal_generation,
            subtitle_color=subtitle_color,
            subtitle_outline_color=subtitle_outline_color,
            sub_names=sub_names,
            sub_size=sub_size,
            subtitle_alignment=subtitle_alignment,
            crop_mode=crop_mode,
            script_values=script_values,
            re_sync=re_sync,
            indexer=self.config.cfg_payload.indexer,
            image_plugin=self.config.cfg_payload.image_plugin,
            source_file=self.source_file,
            source_file_mi_obj=source_file_mi_obj,
        )
        self.queued_worker.job_finished.connect(self._generate_finished)
        self.queued_worker.job_failed.connect(self._generate_failed)
        self.queued_worker.start()

    @Slot(int)
    def _generate_finished(self, code: int) -> None:
        if code == 0:
            ss_mode = self.config.cfg_payload.ss_mode
            if self.context.media_input.comparison_pair:
                ss_mode = (
                    ScreenShotMode.SIMPLE_SS_COMP
                    if self.config.cfg_payload.ss_mode is not ScreenShotMode.ADV_SS_COMP
                    else ScreenShotMode.ADV_SS_COMP
                )

            if not self.image_dir:
                raise RuntimeError("Failed to determine image_dir")
            self.image_viewer = ImageViewer(
                image_base_dir=self.image_dir,
                comparison_mode=ss_mode,
                min_required_selected_screens=self.config.cfg_payload.min_required_selected_screens,
                max_required_selected_screens=self.config.cfg_payload.max_required_selected_screens,
                parent=self,
            )
            self.image_viewer.show()
            GSigs().main_window_set_disabled.emit(False)
            self.image_viewer.exit_viewer.connect(lambda i: self._load_images(i, True))
            self.image_viewer.re_sync_images.connect(self._re_sync)
        else:
            QMessageBox.warning(
                self,
                "Error",
                f"Failed to generate images, check logs for more information ({code})",
            )
            self._complete_loading()

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
                and self.config.cfg_payload.ss_mode is ScreenShotMode.BASIC_SS_GEN
            ):
                self.is_comparison_images = False
            elif (
                generated
                and self.config.cfg_payload.ss_mode is not ScreenShotMode.BASIC_SS_GEN
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
        self.source_file = None
        self.media_file = None
        self.image_dir = None
        self.script_values = None
