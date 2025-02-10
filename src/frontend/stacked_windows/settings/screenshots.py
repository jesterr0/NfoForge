from PySide6.QtCore import Slot, QEvent, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
    QMessageBox,
    QWidget,
)
from PySide6.QtGui import QColor, QPalette

from src.enums.screen_shot_mode import ScreenShotMode
from src.enums.cropping import Cropping
from src.enums.indexer import Indexer
from src.enums.image_plugin import ImagePlugin
from src.enums.subtitles import SubtitleAlignment
from src.enums.settings_window import SettingsTabs
from src.frontend.utils import build_h_line, create_form_layout
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.color_selection_shape import ColorSelectionShape
from src.frontend.custom_widgets.image_host_listbox import ImageHostListBox
from src.frontend.stacked_windows.settings.base import BaseSettings


class ScreenShotSettings(BaseSettings):
    def __init__(self, config, main_window, parent) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("screenShotSettings")

        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)

        ss_enabled_lbl = QLabel("Generate Screenshots")
        ss_enabled_lbl.setToolTip("Toggles image generation")
        self.ss_enabled_btn = QCheckBox(self)
        self.ss_enabled_btn.clicked.connect(self._ss_enable_toggle_check)

        ss_count_lbl = QLabel("Screenshot Count", self)
        ss_count_lbl.setToolTip(
            "Sets total number of screenshots generated for user to choose from"
        )
        self.ss_count_spinbox = self._build_spinbox(2, (2, 100), self)

        ss_mode_lbl = QLabel("Screenshot Mode", self)
        self.ss_mode_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )
        self.ss_mode_combo.activated.connect(self._ss_mode_changed)

        ss_optimize_generated_lbl = QLabel("Optimize Generated Images", self)
        ss_optimize_generated_lbl.setToolTip("Optimize generated images (recommended)")
        self.ss_optimize_generated_btn = QCheckBox(self)

        ss_trim_start_lbl = QLabel("Video Start %", self)
        ss_trim_start_lbl.setToolTip(
            "Percentage of video file to trim from start for screenshot generation (max 30%)"
        )
        self.ss_trim_start = self._build_spinbox(
            step=1, min_max_range=(0, 30), parent=self
        )

        ss_trim_end_lbl = QLabel("Video End %", self)
        ss_trim_end_lbl.setToolTip(
            "Percentage of video file to trim from end for screenshot generation (max 30%)"
        )
        self.ss_trim_end = self._build_spinbox(
            step=1, min_max_range=(0, 30), parent=self
        )

        ss_required_count_lbl = QLabel("Required Selected Screenshot Count", self)
        ss_required_count_lbl.setToolTip(
            "Required screenshots/screenshot pairs to be selected before closing Image Viewer"
        )
        self.ss_required_count_spinbox = self._build_spinbox(1, (0, 100), self)

        crop_mode_lbl = QLabel("Crop Mode", self)
        crop_mode_lbl.setToolTip("Sets which cropping method will be used")
        self.crop_mode_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )

        indexer_lbl = QLabel("Image Indexer", self)
        indexer_lbl.setToolTip(
            "Indexing library used to index files for screenshots with FrameForge"
        )
        self.indexer_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )

        image_plugin_lbl = QLabel("Image Plugin", self)
        image_plugin_lbl.setToolTip(
            "Image library used when generating screenshots with FrameForge"
        )
        self.image_plugin_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )

        ss_comparison_subtitle_lbl = QLabel("Comparison Subtitles")
        ss_comparison_subtitle_lbl.setToolTip("Toggles comparison subtitles")
        self.ss_comparison_subtitle_btn = QCheckBox(self)

        ss_comp_source_lbl = QLabel("Comparison Source Subtitles", self)
        ss_comp_source_lbl.setToolTip("Comparison subtitle for source images")
        self.ss_comp_source_entry = QLineEdit(self)

        ss_comp_encode_lbl = QLabel("Comparison Encode Subtitles", self)
        ss_comp_encode_lbl.setToolTip("Comparison subtitle for encode images")
        self.ss_comp_encode_entry = QLineEdit(self)

        sub_720p_size_lbl = QLabel("Subtitle Size (<= 720p)", self)
        sub_720p_size_lbl.setToolTip(
            "Subtitle size for resolution less than or equal to 720p"
        )
        self.sub_720p_size_spinbox = self._build_spinbox(2, (2, 100), self)

        sub_1080p_size_lbl = QLabel("Subtitle Size (<= 1080p)", self)
        sub_1080p_size_lbl.setToolTip(
            "Subtitle size for resolution less than or equal to 1080p"
        )
        self.sub_1080p_size_spinbox = self._build_spinbox(2, (2, 100), self)

        sub_2160p_size_lbl = QLabel("Subtitle Size (> 1080p)", self)
        sub_2160p_size_lbl.setToolTip("Subtitle size for resolution greater than 1080p")
        self.sub_2160p_size_spinbox = self._build_spinbox(2, (2, 100), self)

        sub_color_lbl = QLabel("Subtitle Color (hex: #f5c70a)", self)
        sub_color_lbl.setToolTip("Subtitle color (must be specified as a hex value)")

        self.sub_color_picker = ColorSelectionShape(width=14, height=14, parent=self)
        self.sub_color_picker.setToolTip("Set subtitle color")
        self.sub_color_picker.color_changed.connect(self._update_sub_entry_color)

        self.sub_color_entry = QLineEdit(self)
        self.sub_color_entry.setReadOnly(True)

        sub_lbl_color_widget = QWidget()
        sub_lbl_color_layout = QHBoxLayout(sub_lbl_color_widget)
        sub_lbl_color_layout.setContentsMargins(0, 0, 0, 0)
        sub_lbl_color_layout.addWidget(sub_color_lbl)
        sub_lbl_color_layout.addWidget(
            self.sub_color_picker, alignment=Qt.AlignmentFlag.AlignRight
        )

        sub_alignment_lbl = QLabel("Subtitle Alignment", self)
        sub_alignment_lbl.setToolTip("Adjust subtitle position")
        self.sub_alignment_combo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )

        dl_provided_images_optimize_lbl = QLabel(
            "Convert downloaded and opened images to optimized PNG format", self
        )
        dl_provided_images_optimize_lbl.setToolTip(
            "Converts images from downloaded URLs and opened files to PNG format, "
            "optimizing them for re-uploading to another image host."
        )
        self.dl_provided_images_optimize = QCheckBox(self)

        self.optimize_cpu_cores_percent_lbl = QLabel(self)
        self.optimize_cpu_cores_percent_lbl.setToolTip(
            "Will calculate percentage of CPUs to use based on a percentage (8 threads at 0.5% = 4 threads)"
        )
        self.optimize_cpu_cores_percent = QDoubleSpinBox(self)
        self.optimize_cpu_cores_percent.setStepType(
            QDoubleSpinBox.StepType.AdaptiveDecimalStepType
        )
        self.optimize_cpu_cores_percent.setSingleStep(0.1)
        self.optimize_cpu_cores_percent.setRange(0.1, 1.0)
        self.optimize_cpu_cores_percent.wheelEvent = self._disable_scrollwheel_spinbox
        self.optimize_cpu_cores_percent.valueChanged.connect(self._optimize_cpu_changed)

        image_host_config_label = QLabel("Image Hosts Configuration", self)
        self.image_host_config = ImageHostListBox(self.config, self)
        self.image_host_config.setMinimumHeight(180)

        self.add_layout(create_form_layout(ss_enabled_lbl, self.ss_enabled_btn))
        self.add_layout(create_form_layout(ss_count_lbl, self.ss_count_spinbox))
        self.add_layout(create_form_layout(ss_mode_lbl, self.ss_mode_combo))
        self.add_layout(
            create_form_layout(
                ss_optimize_generated_lbl, self.ss_optimize_generated_btn
            )
        )
        self.add_layout(create_form_layout(ss_trim_start_lbl, self.ss_trim_start))
        self.add_layout(create_form_layout(ss_trim_end_lbl, self.ss_trim_end))
        self.add_layout(
            create_form_layout(ss_required_count_lbl, self.ss_required_count_spinbox)
        )
        self.add_layout(create_form_layout(crop_mode_lbl, self.crop_mode_combo))
        self.add_layout(create_form_layout(indexer_lbl, self.indexer_combo))
        self.add_layout(create_form_layout(image_plugin_lbl, self.image_plugin_combo))
        self.add_widget(build_h_line((10, 1, 10, 1)))
        self.add_layout(
            create_form_layout(
                ss_comparison_subtitle_lbl, self.ss_comparison_subtitle_btn
            )
        )
        self.add_layout(
            create_form_layout(ss_comp_source_lbl, self.ss_comp_source_entry)
        )
        self.add_layout(
            create_form_layout(ss_comp_encode_lbl, self.ss_comp_encode_entry)
        )
        self.add_widget(build_h_line((10, 1, 10, 1)))
        self.add_layout(
            create_form_layout(sub_720p_size_lbl, self.sub_720p_size_spinbox)
        )
        self.add_layout(
            create_form_layout(sub_1080p_size_lbl, self.sub_1080p_size_spinbox)
        )
        self.add_layout(
            create_form_layout(sub_2160p_size_lbl, self.sub_2160p_size_spinbox)
        )
        self.add_layout(create_form_layout(sub_lbl_color_widget, self.sub_color_entry))
        self.add_layout(create_form_layout(sub_alignment_lbl, self.sub_alignment_combo))
        self.add_widget(build_h_line((10, 1, 10, 1)))
        self.add_layout(
            create_form_layout(
                dl_provided_images_optimize_lbl, self.dl_provided_images_optimize
            )
        )
        self.add_layout(
            create_form_layout(
                self.optimize_cpu_cores_percent_lbl, self.optimize_cpu_cores_percent
            )
        )
        self.add_widget(build_h_line((10, 1, 10, 1)))
        self.add_layout(
            create_form_layout(image_host_config_label, self.image_host_config)
        )
        self.add_layout(self.reset_layout)

        self._load_saved_settings()

    def _ss_toggle_check(self, ss_mode: ScreenShotMode) -> None:
        if ss_mode in (
            ScreenShotMode.BASIC_SS_GEN,
            ScreenShotMode.SIMPLE_SS_COMP,
        ):
            ffmpeg = self.config.cfg_payload.ffmpeg
            if not ffmpeg or (ffmpeg and not ffmpeg.exists()):
                QMessageBox.critical(
                    self,
                    "Dependency Error",
                    (
                        "FFMPEG isn't detected and is required for basic and "
                        "simple comparison screenshots.\n\nDisabling image "
                        "generation until executable path is provided."
                    ),
                )
                self.config.cfg_payload.screenshots_enabled = False
                self.ss_enabled_btn.setChecked(False)
                self.config.save_config()
                self.settings_window.swap_tab.emit(SettingsTabs.DEPENDENCIES_SETTINGS)

        elif ss_mode == ScreenShotMode.ADV_SS_COMP:
            frame_forge = self.config.cfg_payload.frame_forge
            if not frame_forge or (frame_forge and not frame_forge.exists()):
                QMessageBox.critical(
                    self,
                    "Dependency Error",
                    (
                        "FrameForge isn't detected and is required for advanced "
                        "comparison screenshots.\n\nDisabling image "
                        "generation until executable path is provided."
                    ),
                )
                self.config.cfg_payload.screenshots_enabled = False
                self.ss_enabled_btn.setChecked(False)
                self.config.save_config()
                self.settings_window.swap_tab.emit(SettingsTabs.DEPENDENCIES_SETTINGS)

    @Slot(bool)
    def _ss_enable_toggle_check(self, _: bool) -> None:
        if self.ss_enabled_btn.isChecked():
            self._ss_toggle_check(self.config.cfg_payload.ss_mode)

    @Slot(int)
    def _ss_mode_changed(self, idx: int) -> None:
        if idx > -1:
            self._ss_toggle_check(self.ss_mode_combo.currentData())

    @Slot(object)
    def _update_sub_entry_color(self, color: QColor) -> None:
        palette = self.sub_color_entry.palette()
        palette.setColor(QPalette.ColorRole.Text, color)
        self.sub_color_entry.setPalette(palette)
        self.sub_color_entry.setText(self.sub_color_picker.get_hex_color())

    @Slot(float)
    def _optimize_cpu_changed(self, value: float) -> None:
        """When optimize spinbox is changed the label is automatically populated"""
        self.optimize_cpu_cores_percent_lbl.setText(
            f"Optimize Images CPU Percent ({value:.0%})"
        )

    @Slot()
    def _load_saved_settings(self) -> None:
        """Applies user saved settings from the config"""
        payload = self.config.cfg_payload
        self.ss_enabled_btn.setChecked(payload.screenshots_enabled)
        self.ss_count_spinbox.setValue(payload.screen_shot_count)
        self.load_combo_box(self.ss_mode_combo, ScreenShotMode, payload.ss_mode)
        self.ss_optimize_generated_btn.setChecked(payload.compress_images)
        self.ss_trim_start.setValue(payload.trim_start)
        self.ss_trim_end.setValue(payload.trim_end)
        self.ss_required_count_spinbox.setValue(payload.required_selected_screens)
        self.load_combo_box(self.crop_mode_combo, Cropping, payload.crop_mode)
        self.load_combo_box(self.indexer_combo, Indexer, payload.indexer)
        self.load_combo_box(self.image_plugin_combo, ImagePlugin, payload.image_plugin)
        self.ss_comparison_subtitle_btn.setChecked(payload.comparison_subtitles)
        self.ss_comp_source_entry.setText(payload.comparison_subtitle_source_name)
        self.ss_comp_encode_entry.setText(payload.comparison_subtitle_encode_name)
        self.sub_720p_size_spinbox.setValue(payload.sub_size_height_720)
        self.sub_1080p_size_spinbox.setValue(payload.sub_size_height_1080)
        self.sub_2160p_size_spinbox.setValue(payload.sub_size_height_2160)
        self.sub_color_entry.setText(payload.subtitle_color)
        self.sub_color_picker.update_color(
            QColor(self.config.cfg_payload.subtitle_color)
        )
        self._update_sub_entry_color(self.sub_color_picker.get_color())
        self.load_combo_box(
            self.sub_alignment_combo, SubtitleAlignment, payload.subtitle_alignment
        )
        self.dl_provided_images_optimize.setChecked(
            self.config.cfg_payload.optimize_dl_url_images
        )
        self.optimize_cpu_cores_percent.setValue(
            self.config.cfg_payload.optimize_dl_url_images_percentage
        )
        self.image_host_config.add_items(self.config.image_host_map)

    @Slot()
    def _save_settings(self) -> None:
        self.config.cfg_payload.screenshots_enabled = self.ss_enabled_btn.isChecked()
        self.config.cfg_payload.screen_shot_count = self.ss_count_spinbox.value()
        self.config.cfg_payload.ss_mode = self.ss_mode_combo.currentData()
        self.config.cfg_payload.compress_images = (
            self.ss_optimize_generated_btn.isChecked()
        )
        self.config.cfg_payload.required_selected_screens = (
            self.ss_required_count_spinbox.value()
        )
        self.config.cfg_payload.crop_mode = self.crop_mode_combo.currentData()
        self.config.cfg_payload.indexer = self.indexer_combo.currentData()
        self.config.cfg_payload.image_plugin = self.image_plugin_combo.currentData()
        self.config.cfg_payload.comparison_subtitles = (
            self.ss_comparison_subtitle_btn.isChecked()
        )
        self.config.cfg_payload.comparison_subtitle_source_name = (
            self.ss_comp_source_entry.text().strip()
        )
        self.config.cfg_payload.comparison_subtitle_encode_name = (
            self.ss_comp_encode_entry.text().strip()
        )
        self.config.cfg_payload.sub_size_height_720 = self.sub_720p_size_spinbox.value()
        self.config.cfg_payload.sub_size_height_1080 = (
            self.sub_1080p_size_spinbox.value()
        )
        self.config.cfg_payload.sub_size_height_2160 = (
            self.sub_2160p_size_spinbox.value()
        )
        self.config.cfg_payload.subtitle_color = self.sub_color_entry.text().strip()
        self.config.cfg_payload.subtitle_alignment = (
            self.sub_alignment_combo.currentData()
        )
        self.config.cfg_payload.optimize_dl_url_images = (
            self.dl_provided_images_optimize.isChecked()
        )
        self.config.cfg_payload.optimize_dl_url_images_percentage = (
            self.optimize_cpu_cores_percent.value()
        )
        try:
            self.image_host_config.validate_settings()
        except AttributeError as attr_error:
            QMessageBox.warning(self, "Warning", str(attr_error))
            return
        self.image_host_config.save_host_info()
        self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self.ss_enabled_btn.setChecked(True)
        self.ss_count_spinbox.setValue(20)
        self.ss_mode_combo.setCurrentIndex(0)
        self.ss_optimize_generated_btn.setChecked(True)
        self.ss_required_count_spinbox.setValue(0)
        self.crop_mode_combo.setCurrentIndex(0)
        self.indexer_combo.setCurrentIndex(0)
        self.image_plugin_combo.setCurrentIndex(0)
        self.ss_comparison_subtitle_btn.setChecked(True)
        self.ss_comp_source_entry.setText("Source")
        self.ss_comp_encode_entry.setText("Encode")
        self.sub_720p_size_spinbox.setValue(12)
        self.sub_1080p_size_spinbox.setValue(16)
        self.sub_2160p_size_spinbox.setValue(32)
        self.sub_color_picker.update_color(QColor("#f5c70a"))
        self._update_sub_entry_color(self.sub_color_picker.get_color())
        self.dl_provided_images_optimize.setChecked(True)
        self.optimize_cpu_cores_percent.setValue(0.25)
        self.image_host_config.add_items(self.config.image_host_map, reset=True)
        self.sub_alignment_combo.setCurrentIndex(0)

    def _build_spinbox(
        self, step: int, min_max_range: tuple[int, int], parent=None
    ) -> QSpinBox:
        spinbox = QSpinBox(parent)
        spinbox.setRange(*min_max_range)
        spinbox.setSingleStep(step)
        spinbox.wheelEvent = self._disable_scrollwheel_spinbox
        return spinbox

    @staticmethod
    def _disable_scrollwheel_spinbox(event: QEvent) -> None:
        event.ignore()
