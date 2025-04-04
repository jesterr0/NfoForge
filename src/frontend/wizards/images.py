from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal, QThread, Slot
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QVBoxLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QMessageBox,
    QStackedWidget,
    QWidget,
    QFrame,
    QFileDialog,
    QScrollArea,
)

from pymediainfo import MediaInfo

from src.config.config import Config
from src.exceptions.utils import get_full_traceback
from src.logger.nfo_forge_logger import LOG
from src.enums.cropping import Cropping
from src.enums.indexer import Indexer
from src.enums.profile import Profile
from src.enums.screen_shot_mode import ScreenShotMode
from src.enums.subtitles import SubtitleAlignment
from src.enums.image_plugin import ImagePlugin
from src.packages.custom_types import CropValues, SubNames, AdvancedResize
from src.backend.images import ImagesBackEnd
from src.backend.utils.images import (
    compare_resolutions,
    determine_sub_size,
    extract_images_from_str,
)
from src.backend.utils.script_parser import ScriptParser
from src.frontend.global_signals import GSigs
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.frontend.custom_widgets.dnd_factory import (
    DNDToolButton,
    DNDThumbnailListWidget,
)
from src.frontend.stacked_windows.cropping import CropWidget
from src.frontend.windows.image_viewer import ImageViewer
from src.frontend.wizards.media_input_basic import MediaInputBasic
from src.frontend.utils import build_auto_theme_icon_buttons, build_v_line

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


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
        crop_values: CropValues | None,
        advanced_resize: AdvancedResize | None,
        re_sync: int,
        indexer: Indexer | None,
        image_plugin: ImagePlugin | None,
        ffmpeg_path: Path,
        frame_forge_path: Path,
        progress_signal: Signal,
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
            crop_values (Optional[CropValues]): Crop values.
            advanced_resize (Optional[AdvancedResize]): Crop values.
            re_sync (int): Re_sync value.
            indexer (Optional[Indexer]): Indexer used for FrameForge.
            image_plugin (Optional[ImagePlugin]): Plugin used for image generation in FrameForge.
            ffmpeg_path (Path): Path to FFMPEG executable.
            frame_forge_path (Path): Path to FFMPEG executable.
            progress_signal (Signal[str, float]): The signal used to emit progress updates.
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
        self.crop_values = crop_values
        self.advanced_resize = advanced_resize
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
        )
        self.job_finished.emit(job)

    def _adv_comparison_generation(self) -> None:
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
        parent: "MainWindow",
    ) -> None:
        super().__init__(config, parent)
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
        self.crop_values: CropValues | None = None
        self.advanced_resize: AdvancedResize | None = None

        self.generate_images = QPushButton("Generate", self)
        self.generate_images.setToolTip("Generates images from media file(s).")
        self.generate_images.clicked.connect(self._generate_images)

        self.progress_bar = QProgressBar(self)

        open_images_btn: DNDToolButton = build_auto_theme_icon_buttons(
            DNDToolButton, "open.svg", "openImageButton", 20, 20, parent=self
        )
        open_images_btn.setToolTip("Use existing generated images (.png, .jpg, .jpeg).")
        open_images_btn.clicked.connect(self._open_images)

        paste_urls: DNDToolButton = build_auto_theme_icon_buttons(
            DNDToolButton, "paste_clipboard.svg", "pasteURLsButton", 20, 20, parent=self
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

        self.cropping_widget = CropWidget()
        self.cropping_widget.crop_confirmed.connect(self._execute_image_generation)

        self.stacked_widget = QStackedWidget(self)
        self.stacked_widget.addWidget(self.main_scroll_area)
        self.stacked_widget.addWidget(self.cropping_widget)

        final_layout = QVBoxLayout(self)
        final_layout.setContentsMargins(0, 0, 0, 0)
        final_layout.addWidget(self.stacked_widget)

        self.setLayout(final_layout)

    def isComplete(self) -> bool:
        """Overrides isComplete method to control the next button"""
        return self.loading_complete

    def validatePage(self) -> bool:
        """Overrides validatePage method to run additional tasks"""
        if (
            not self.config.shared_data.loaded_images
            and not self.config.shared_data.url_data
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
        if self.config.shared_data.loaded_images:
            img_path_data = "\n".join(
                (str(p) for p in self.config.shared_data.loaded_images)
            )
            LOG.info(
                LOG.LOG_SOURCE.FE,
                f"#### IMG Path Data ####\n{img_path_data}\n#### IMG Path Data ####",
            )
        if self.config.shared_data.url_data:
            img_url_data = "\n".join(
                (str(url_d) for url_d in self.config.shared_data.url_data)
            )
            LOG.info(
                LOG.LOG_SOURCE.FE,
                f"#### IMG URL Data ####\n{img_url_data}\n#### IMG URL Data ####",
            )

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
        profile = self.config.cfg_payload.profile
        ss_mode = self.config.cfg_payload.ss_mode
        crop_mode = self.config.cfg_payload.crop_mode

        # over ride profile if the user is using the Basic (Built-in) plugin
        if profile == Profile.PLUGIN:
            if self.config.cfg_payload.wizard_page:
                wizard_plugin = self.config.loaded_plugins[
                    self.config.cfg_payload.wizard_page
                ].wizard
                if wizard_plugin == MediaInputBasic:
                    self.config.cfg_payload.profile = profile = Profile.BASIC

        if profile == Profile.BASIC:
            self._execute_image_generation()
        elif profile in (Profile.ADVANCED, Profile.PLUGIN):
            if ss_mode == ScreenShotMode.BASIC_SS_GEN:
                self._execute_image_generation()
            elif ss_mode == ScreenShotMode.SIMPLE_SS_COMP:
                if not self._compare_resolutions():
                    if crop_mode == Cropping.MANUAL:
                        self.stacked_widget.setCurrentWidget(self.cropping_widget)
                        return
                self._execute_image_generation()

            elif ss_mode == ScreenShotMode.ADV_SS_COMP:
                if not self._compare_resolutions():
                    if crop_mode == Cropping.MANUAL:
                        if self.config.media_input_payload.script_file:
                            script_str = self._read_advanced_script(
                                self.config.media_input_payload.script_file
                            )
                            advanced_script_data = ScriptParser(script_str).get_data()
                            self._execute_image_generation(
                                advanced_script_data.crop_values,
                                advanced_script_data.advanced_resize,
                            )
                        else:
                            self.stacked_widget.setCurrentWidget(self.cropping_widget)
                            return
                self._execute_image_generation()

    def _compare_resolutions(self) -> bool:
        if (
            not self.config.media_input_payload.source_file_mi_obj
            or not self.config.media_input_payload.encode_file_mi_obj
        ):
            raise AttributeError("Cannot detect MediaInfo for source or encode input")
        if not compare_resolutions(
            self.config.media_input_payload.source_file_mi_obj,
            self.config.media_input_payload.encode_file_mi_obj,
        ):
            return False
        return True

    def _read_advanced_script(self, script: PathLike[str]) -> str:
        with open(script, "r", encoding="utf-8") as read_script:
            return read_script.read()

    @Slot()
    def _execute_image_generation(
        self,
        crop_values: CropValues | None = None,
        advanced_resize: AdvancedResize | None = None,
        re_sync: int = 0,
    ) -> None:
        crop_mode = self.config.cfg_payload.crop_mode
        if crop_values:
            self.crop_values = crop_values

        if advanced_resize:
            self.advanced_resize = advanced_resize

        self.stacked_widget.setCurrentWidget(self.main_scroll_area)

        if self.queued_worker is not None and self.queued_worker.isRunning():
            return

        GSigs().main_window_set_disabled.emit(True)
        self.text_box.clear()
        self.thumbnail_listbox.clear()
        self._disable_generate_images_button()
        self._update_loading_state(False)

        profile_handlers = {
            Profile.BASIC: self._handle_basic_profile,
            Profile.ADVANCED: self._handle_basic_comparison,
            Profile.PLUGIN: self._handle_plugin_profile,
        }

        profile = Profile(self.config.cfg_payload.profile)
        handler = profile_handlers[profile]
        ss_mode, source_file_mi_obj, media_file_mi_obj, comparison_subs = handler()
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
            crop_values,
            advanced_resize,
            re_sync,
        )

    def _disable_generate_images_button(self) -> None:
        self.generate_images.setEnabled(False)

    def _update_loading_state(self, state: bool) -> None:
        self.loading_complete = state
        self.completeChanged.emit()

    def _handle_basic_profile(self) -> tuple:
        if not self.config.media_input_payload.encode_file:
            raise FileNotFoundError("Failed to locate path to 'encode_file'")
        self.media_file = Path(self.config.media_input_payload.encode_file)
        return (
            ScreenShotMode.BASIC_SS_GEN,
            None,
            self.config.media_input_payload.encode_file_mi_obj,
            False,
        )

    def _handle_basic_comparison(self) -> tuple:
        if (
            not self.config.media_input_payload.source_file
            or not self.config.media_input_payload.encode_file
        ):
            raise FileNotFoundError(
                "Failed to locate path to 'source_file' or 'encode_file'"
            )
        self.source_file = Path(self.config.media_input_payload.source_file)
        source_file_mi_obj = self.config.media_input_payload.source_file_mi_obj
        self.media_file = Path(self.config.media_input_payload.encode_file)
        media_file_mi_obj = self.config.media_input_payload.encode_file_mi_obj
        comparison_subs = self.config.cfg_payload.comparison_subtitles
        return (
            self.config.cfg_payload.ss_mode,
            source_file_mi_obj,
            media_file_mi_obj,
            comparison_subs,
        )

    def _handle_plugin_profile(self) -> tuple:
        if (
            not self.config.media_input_payload.source_file
            or not self.config.media_input_payload.encode_file
        ):
            raise FileNotFoundError(
                "Failed to locate path to 'source_file' or 'encode_file'"
            )
        self.source_file = Path(self.config.media_input_payload.source_file)
        source_file_mi_obj = self.config.media_input_payload.source_file_mi_obj
        self.media_file = Path(self.config.media_input_payload.encode_file)
        media_file_mi_obj = self.config.media_input_payload.encode_file_mi_obj
        comparison_subs = self.config.cfg_payload.comparison_subtitles
        return (
            self.config.cfg_payload.ss_mode,
            source_file_mi_obj,
            media_file_mi_obj,
            comparison_subs,
        )

    def _set_image_directory(self) -> None:
        if not self.media_file:
            raise FileNotFoundError("Failed to locate path to 'media_file'")
        self.image_dir = self.media_file.parent / f"{self.media_file.stem}_images"

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
        crop_values: CropValues | None,
        advanced_resize: AdvancedResize | None,
        re_sync,
    ) -> None:
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
            crop_values=crop_values,
            advanced_resize=advanced_resize,
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
            if self.config.cfg_payload.profile == Profile.BASIC:
                ss_mode = ScreenShotMode.BASIC_SS_GEN

            self.image_viewer = ImageViewer(
                self.image_dir,
                ss_mode,
                self.config.cfg_payload.required_selected_screens,
                self,
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
        self._update_text_box("Successfully parsed images!")
        self.thumbnail_listbox.addItems([str(x) for x in img_objs])
        self.config.shared_data.url_data = img_objs
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
            self.config.shared_data.loaded_images = images
            self.config.shared_data.generated_images = generated
        self._complete_loading()

    @Slot(int)
    def _re_sync(self, offset: int) -> None:
        self._execute_image_generation(
            crop_values=self.crop_values,
            advanced_resize=self.advanced_resize,
            re_sync=offset,
        )

    def _complete_loading(self) -> None:
        GSigs().main_window_set_disabled.emit(False)
        self.generate_images.setEnabled(True)
        self._update_loading_state(True)

        self.source_file = None
        self.media_file = None
        self.image_dir = None
        self.crop_values = None
        self.advanced_resize = None

    @Slot()
    def reset_page(self) -> None:
        self.text_box.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.reset()
        self.thumbnail_listbox.clear()
        self.stacked_widget.setCurrentWidget(self.main_scroll_area)
        self.main_scroll_area.verticalScrollBar().setValue(
            self.main_scroll_area.verticalScrollBar().minimum()
        )
