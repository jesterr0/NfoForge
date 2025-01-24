from os import PathLike
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING, Iterable, Union

from PySide6.QtCore import Signal, QThread, Slot
from PySide6.QtWidgets import (
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
    QSpacerItem,
    QSizePolicy,
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
from src.enums.image_host import ImageHost
from src.enums.image_plugin import ImagePlugin
from src.enums.url_type import URLType
from src.packages.custom_types import (
    CropValues,
    SubNames,
    AdvancedResize,
    ImageUploadData,
)
from src.backend.images import ImagesBackEnd
from src.backend.utils.images import compare_resolutions, determine_sub_size
from src.backend.utils.script_parser import ScriptParser
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.frontend.custom_widgets.dnd_factory import (
    DNDToolButton,
    DNDThumbnailListWidget,
)
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.url_organizer import URLOrganizer
from src.frontend.stacked_windows.cropping import CropWidget
from src.frontend.windows.image_viewer import ImageViewer
from src.frontend.utils import build_auto_theme_icon_buttons, build_h_line

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
        sub_names: Optional[SubNames],
        sub_size: int,
        subtitle_alignment: SubtitleAlignment,
        crop_values: Optional[CropValues],
        advanced_resize: Optional[AdvancedResize],
        re_sync: int,
        compression: bool,
        indexer: Optional[Indexer],
        image_plugin: (Optional[ImagePlugin]),
        ffmpeg_path: Path,
        frame_forge_path: Path,
        progress_signal: Signal,
        source_file: Optional[Path] = None,
        source_file_mi_obj: Optional[MediaInfo] = None,
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
            sub_names (Optional[SubNames]): Subtitle names.
            sub_size (int): Subtitle size.
            subtitle_alignment (SubtitleAlignment): Subtitle alignment.
            crop_values (Optional[CropValues]): Crop values.
            advanced_resize (Optional[AdvancedResize]): Crop values.
            re_sync (int): Re_sync value.
            compression (bool): If we want to compress the images.
            indexer (Optional[Indexer]): Indexer used for FrameForge.
            image_plugin (Optional[ImagePlugin]): Plugin used for image generation in FrameForge.
            ffmpeg_path (Path): Path to FFMPEG executable.
            frame_forge_path (Path): Path to FFMPEG executable.
            progress_signal (Signal[str, float]): The signal used to emit progress updates.
            source_file (Optional[Path]): The input file path for the source.
            source_file_mi_obj (Optional[Path]): MediaInfo object of the input file.
        """
        super().__init__()
        self.backend = backend
        self.ss_mode = ss_mode
        self.media_file = media_file
        self.media_file_mi_obj = media_file_mi_obj
        self.output_directory = output_directory
        self.total_images = total_images
        self.trim = trim
        self.subtitle_color = subtitle_color
        self.sub_names = sub_names
        self.sub_size = sub_size
        self.subtitle_alignment = subtitle_alignment
        self.crop_values = crop_values
        self.advanced_resize = advanced_resize
        self.re_sync = re_sync
        self.compression = compression
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
            self.compression,
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
            self.sub_names,
            self.sub_size,
            self.crop_values,
            self.compression,
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
            self.sub_names,
            self.sub_size,
            self.subtitle_alignment,
            self.crop_values,
            self.advanced_resize,
            self.re_sync,
            self.compression,
            self.indexer,
            self.image_plugin,
            self.frame_forge_path,
            self.progress_signal,
        )
        self.job_finished.emit(job)


class QueuedWorkerUploader(QThread):
    job_finished = Signal(object)
    job_failed = Signal(str)

    def __init__(
        self,
        backend: ImagesBackEnd,
        config: Config,
        filepaths: Iterable[Union[PathLike[str], Path]],
        progress_signal: Signal,
    ) -> None:
        """
        Handles uploading images to image hosts.

        Parameters:
            backend (ImagesBackEnd): ImagesBackEnd class.
            config (Config): Config class.
            filepaths (Iterable[Union[PathLike[str], Path]]): Iterable object of filepaths.
            progress_signal (Signal[str, float]): The signal used to emit progress updates.

        Returns:
            Dictionary object numbered with ImageUploadData.
        """
        super().__init__()
        self.backend = backend
        self.config = config
        self.filepaths = filepaths
        self.progress_signal = progress_signal

    def run(self) -> None:
        try:
            urls = self.backend.upload_images(
                self.config,
                self.filepaths,
                self.progress_signal,
            )
            self.job_finished.emit(urls)
        except Exception as e:
            LOG.error(LOG.LOG_SOURCE.FE, get_full_traceback(e))
            self.job_failed.emit(f"Error: Please check logs for more details ({e})")


class ImagesPage(BaseWizardPage):
    progress_signal_generation = Signal(str, float)
    progress_signal_uploader = Signal(str, float)

    def __init__(
        self,
        config: Config,
        parent: "MainWindow",
    ) -> None:
        super().__init__(config, parent)
        self.setTitle("Images")
        self.setObjectName("imagesPage")
        self.setCommitPage(True)

        self.main_window = parent

        self.config = config
        self.save_config = False
        self.backend = ImagesBackEnd()
        self.loading_complete = False
        self.loaded_images = None

        self.queued_worker: QueuedWorker | None = None
        self.progress_signal_generation.connect(self._progress_callback)
        self.progress_signal_uploader.connect(self._progress_uploader_callback)

        self.queued_worker_uploader: QueuedWorkerUploader | None = None

        self.image_viewer: ImageViewer | None = None
        self.source_file: Path | None = None
        self.media_file: Path | None = None
        self.image_dir: Path | None = None
        self.crop_values: CropValues | None = None
        self.advanced_resize: AdvancedResize | None = None

        self.text_box = QPlainTextEdit(self)
        self.text_box.setFrameShape(QFrame.Shape.Box)
        self.text_box.setFrameShadow(QFrame.Shadow.Sunken)
        self.text_box.setReadOnly(True)
        self.text_box.ensureCursorVisible()
        self.text_box.setMinimumHeight(150)

        open_images_btn: DNDToolButton = build_auto_theme_icon_buttons(
            DNDToolButton, "open.svg", "openImageButton", 24, 18, parent=self
        )
        open_images_btn.setToolTip("Use existing generated images.")
        open_images_btn.clicked.connect(self._open_images)
        self.progress_bar = QProgressBar(self)

        self.generate_images = QPushButton("Generate", self)
        self.generate_images.setMaximumWidth(150)
        self.generate_images.setToolTip(
            "Generates images from media file(s).\n\nAlternatively, you can drag "
            "and drop or open previously generated images below."
        )
        self.generate_images.clicked.connect(self._generate_images)

        progress_layout = QHBoxLayout()
        progress_layout.addWidget(open_images_btn, stretch=1)
        progress_layout.addWidget(self.progress_bar, stretch=10)
        progress_layout.addWidget(self.generate_images)

        self.thumbnail_listbox = DNDThumbnailListWidget(self)
        self.thumbnail_listbox.setMinimumHeight(250)
        self.thumbnail_listbox.setFrameShape(QFrame.Shape.Box)
        self.thumbnail_listbox.setFrameShadow(QFrame.Shadow.Sunken)

        for dnd_widget in (open_images_btn, self.thumbnail_listbox):
            dnd_widget.set_extensions((".png",))
            dnd_widget.set_accept_dir(True)
            dnd_widget.dropped.connect(self._handle_image_drop)

        image_gen_box = QGroupBox("Generation")
        image_gen_box_layout = QVBoxLayout(image_gen_box)
        image_gen_box_layout.addWidget(self.text_box)
        image_gen_box_layout.addLayout(progress_layout)
        image_gen_box_layout.addWidget(self.thumbnail_listbox)

        self.image_host_selection = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )
        self.image_host_selection.activated.connect(self._img_selection_changed)

        upload_images_btn = QPushButton("Upload", self)
        upload_images_btn.setMaximumWidth(150)
        upload_images_btn.clicked.connect(self.upload_images)

        image_host_controls = QHBoxLayout()
        image_host_controls.addWidget(self.image_host_selection, stretch=5)
        image_host_controls.addWidget(upload_images_btn)

        self.upload_progress_bar = QProgressBar()

        self.upload_images_box = QGroupBox("Upload")
        self.upload_images_box.setEnabled(False)
        upload_images_box_layout = QVBoxLayout(self.upload_images_box)
        upload_images_box_layout.addLayout(image_host_controls)
        upload_images_box_layout.addWidget(self.upload_progress_bar)

        self.url_organizer = URLOrganizer(
            remove_margins=True,
            alt_text=self.config.cfg_payload.urls_alt,
            columns=self.config.cfg_payload.urls_columns,
            vertical=self.config.cfg_payload.urls_vertical,
            horizontal=self.config.cfg_payload.urls_horizontal,
            url_mode=self.config.cfg_payload.urls_mode,
            url_type=self.config.cfg_payload.urls_type,
            image_width=self.config.cfg_payload.urls_image_width,
            manual_control=self.config.cfg_payload.urls_manual,
        )
        self.url_organizer.text_area.setMinimumHeight(250)
        self.url_organizer.settings_changed.connect(self._save_config)

        self.urls_box = QGroupBox("URLs")
        self.urls_box.setEnabled(False)
        urls_box_layout = QVBoxLayout(self.urls_box)
        urls_box_layout.addWidget(self.url_organizer)

        main_layout = QVBoxLayout()
        main_layout.addWidget(image_gen_box)
        main_layout.addSpacerItem(
            QSpacerItem(20, 6, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        )
        main_layout.addWidget(build_h_line((10, 1, 10, 1)))
        main_layout.addWidget(self.upload_images_box)
        main_layout.addWidget(self.urls_box)
        main_layout.addSpacerItem(
            QSpacerItem(
                20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
            )
        )
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
        final_layout.addWidget(self.stacked_widget)

        self.setLayout(final_layout)

    def isComplete(self) -> bool:
        """Overrides isComplete method to control the next button"""
        return self.loading_complete

    def initializePage(self) -> None:
        for host_item in ImageHost:
            self.image_host_selection.addItem(str(host_item), host_item.name)
        image_host_selection_cur_idx = self.image_host_selection.findText(
            str(self.config.cfg_payload.image_host)
        )
        if image_host_selection_cur_idx >= 0:
            self.image_host_selection.setCurrentIndex(image_host_selection_cur_idx)

    def validatePage(self) -> bool:
        """Overrides validatePage method to run additional tasks"""
        # update shared_data
        url_data = self.url_organizer.get_urls()
        if not url_data:
            if (
                QMessageBox.question(
                    self,
                    "Continue",
                    "Missing URL data, would you like continue without including screenshots?",
                )
                is QMessageBox.StandardButton.No
            ):
                return False

        # TODO: re work this PER nfo some how when refactor for jinja is added
        self.config.cfg_payload.urls_alt = self.url_organizer.image_alt.text().strip()
        self.config.cfg_payload.urls_columns = (
            self.url_organizer.column_spin_box.value()
        )
        self.config.cfg_payload.urls_vertical = (
            self.url_organizer.vertical_space_spin_box.value()
        )
        self.config.cfg_payload.urls_horizontal = (
            self.url_organizer.horizontal_space_spin_box.value()
        )
        self.config.cfg_payload.urls_mode = int(
            self.url_organizer.linked_toggle.isChecked()
        )
        self.config.cfg_payload.urls_type = URLType(
            self.url_organizer.url_type_selection.currentData()
        )
        self.config.cfg_payload.urls_image_width = (
            self.url_organizer.width_spinbox.value()
        )
        self.config.cfg_payload.urls_manual = int(
            self.url_organizer.manual_toggle.isChecked()
        )

        if self.save_config:
            self.config.save_config()

        self.config.shared_data.url_data = url_data
        if url_data:
            LOG.info(
                LOG.LOG_SOURCE.FE, f"## IMG URLs ##\n{url_data.strip()}\n## IMG URLs ##"
            )
        self.config.shared_data.loaded_images = self.loaded_images
        self.reset_page()

        return True

    def upload_images(self) -> None:
        self._reset_loading_state()
        self.main_window.set_disabled.emit(True)
        self.queued_worker_uploader = QueuedWorkerUploader(
            backend=self.backend,
            config=self.config,
            filepaths=self.loaded_images,
            progress_signal=self.progress_signal_uploader,
        )
        self.queued_worker_uploader.job_finished.connect(self._upload_images_finished)
        self.queued_worker_uploader.job_failed.connect(self._upload_images_failed)
        self.queued_worker_uploader.start()

    @Slot(str, float)
    def _progress_uploader_callback(self, _: str, progress: float):
        self.upload_progress_bar.setValue(progress)

    @Slot(object)
    def _upload_images_finished(
        self, data: Optional[Dict[int, ImageUploadData]]
    ) -> None:
        self.main_window.set_disabled.emit(False)
        self._complete_loading()
        if data:
            self.url_organizer.load_data(data)
            self.urls_box.setEnabled(True)

    @Slot(dict)
    def _upload_images_failed(self, e: str) -> None:
        self.main_window.set_disabled.emit(False)
        self._complete_loading()
        LOG.debug(LOG.LOG_SOURCE.FE, e)
        QMessageBox.critical(self, "Error", e)

    def _save_config(self) -> None:
        self.save_config = True

    @Slot(str, float)
    def _progress_callback(self, line: str, progress: float) -> None:
        self.text_box.appendPlainText(line)
        self.progress_bar.setValue(int(progress))

    @Slot()
    def _generate_images(self) -> None:
        profile = self.config.cfg_payload.profile
        ss_mode = self.config.cfg_payload.ss_mode
        crop_mode = self.config.cfg_payload.crop_mode

        if profile == Profile.BASIC:
            self._execute_image_generation()
        elif profile in (Profile.ADVANCED, Profile.PLUGIN):
            if ss_mode == ScreenShotMode.BASIC_SS_GEN:
                self._execute_image_generation()
            elif ss_mode == ScreenShotMode.SIMPLE_SS_COMP:
                if not compare_resolutions(
                    self.config.media_input_payload.source_file_mi_obj,
                    self.config.media_input_payload.encode_file_mi_obj,
                ):
                    if crop_mode == Cropping.MANUAL:
                        self.stacked_widget.setCurrentWidget(self.cropping_widget)
                        return
                self._execute_image_generation()

            elif ss_mode == ScreenShotMode.ADV_SS_COMP:
                if not compare_resolutions(
                    self.config.media_input_payload.source_file_mi_obj,
                    self.config.media_input_payload.encode_file_mi_obj,
                ):
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

    @Slot(int)
    def _img_selection_changed(self, idx: int) -> None:
        selected_host = ImageHost(idx)
        if selected_host != self.config.cfg_payload.image_host:
            self.config.cfg_payload.image_host = selected_host
            self._save_config()

    def _read_advanced_script(self, script: PathLike[str]) -> str:
        with open(script, "r", encoding="utf-8") as read_script:
            return read_script.read()

    @Slot()
    def _execute_image_generation(
        self,
        crop_values: Optional[CropValues] = None,
        advanced_resize: Optional[AdvancedResize] = None,
        re_sync: int = 0,
    ) -> None:
        # TODO: check to ensure both of these are correct if ran more than once!
        if crop_values:
            self.crop_values = crop_values

        if advanced_resize:
            self.advanced_resize = advanced_resize

        self.stacked_widget.setCurrentWidget(self.main_scroll_area)

        if self.queued_worker is not None and self.queued_worker.isRunning():
            return

        self.main_window.set_disabled.emit(True)
        self.text_box.clear()
        self.thumbnail_listbox.clear()
        self._disable_generate_images_button()
        self._reset_loading_state()

        profile_handlers = {
            Profile.BASIC: self._handle_basic_profile,
            Profile.ADVANCED: self._handle_basic_comparison,
            Profile.PLUGIN: self._handle_plugin_profile,
        }

        profile = Profile(self.config.cfg_payload.profile)
        handler = profile_handlers.get(profile)
        ss_mode, source_file_mi_obj, media_file_mi_obj, comparison_subs = handler()

        self._set_image_directory()

        subtitle_color = self.config.cfg_payload.subtitle_color
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
            sub_names,
            sub_size,
            subtitle_alignment,
            crop_values,
            advanced_resize,
            re_sync,
        )

    def _disable_generate_images_button(self) -> None:
        self.generate_images.setEnabled(False)

    def _reset_loading_state(self) -> None:
        self.loading_complete = False
        self.completeChanged.emit()

    def _handle_basic_profile(self) -> tuple:
        self.media_file = Path(self.config.media_input_payload.encode_file)
        return (
            ScreenShotMode.BASIC_SS_GEN,
            None,
            self.config.media_input_payload.encode_file_mi_obj,
            False,
        )

    def _handle_basic_comparison(self) -> tuple:
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
        self.image_dir = self.media_file.parent / f"{self.media_file.stem}_images"

    def _get_sub_names(self, comparison_subs) -> Optional[SubNames]:
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
        sub_names,
        sub_size,
        subtitle_alignment,
        crop_values: Optional[CropValues],
        advanced_resize: Optional[AdvancedResize],
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
            sub_names=sub_names,
            sub_size=sub_size,
            subtitle_alignment=subtitle_alignment,
            crop_values=crop_values,
            advanced_resize=advanced_resize,
            re_sync=re_sync,
            compression=self.config.cfg_payload.compress_images,
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
            self.main_window.set_disabled.emit(False)
            self.image_viewer.exit_viewer.connect(self._load_images)
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
    def _open_images(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            caption="Open Image File(s)", filter="*.png"
        )
        if files:
            self._load_images(files)

    @Slot(list)
    def _handle_image_drop(self, image_s: List[Path]) -> None:
        if not image_s:
            return

        images_only = [img for img in image_s if img.is_file()] + [
            sub_img for img in image_s if img.is_dir() for sub_img in img.glob("*.png")
        ]

        self._load_images(images_only)

    @Slot(list)
    def _load_images(self, images: List[Path]) -> None:
        self.generate_images.setEnabled(True)
        self.urls_box.setEnabled(True)
        self.thumbnail_listbox.clear()
        if images:
            for img in images:
                self.thumbnail_listbox.add_thumbnail(str(img))
            self.upload_images_box.setEnabled(True)
            self.loaded_images = images
        self._complete_loading()

    @Slot(int)
    def _re_sync(self, offset: int) -> None:
        self._execute_image_generation(
            crop_values=self.crop_values,
            advanced_resize=self.advanced_resize,
            re_sync=offset,
        )

    def _complete_loading(self) -> None:
        self.main_window.set_disabled.emit(False)
        self.generate_images.setEnabled(True)
        self.loading_complete = True
        self.completeChanged.emit()

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
        self.upload_progress_bar.setValue(0)
        self.upload_progress_bar.reset()
        self.thumbnail_listbox.clear()
        self.loaded_images = None
        self.url_organizer.reset()
        self.stacked_widget.setCurrentWidget(self.main_scroll_area)
        self.main_scroll_area.verticalScrollBar().setValue(
            self.main_scroll_area.verticalScrollBar().minimum()
        )
