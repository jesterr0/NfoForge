from pathlib import Path
import re
from typing import List

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.backend.utils.script_parser import ScriptParser
from src.frontend.custom_widgets.basic_code_editor import HighlightKeywords
from src.frontend.custom_widgets.dnd_factory import DNDCodeEditor
from src.frontend.utils import build_v_line, set_top_parent_geometry
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from src.packages.custom_types import CropValues
from src.payloads.script import ScriptValues


class CropWidget(QWidget):
    crop_confirmed = Signal(ScriptValues)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.parsed_script: ScriptValues | None = None

        self.cropping_group = QGroupBox("Crop")

        desc_lbl = QLabel(
            "Open an AviSynth or VapourSynth script for automatic detection",
            self.cropping_group,
        )

        input_button = QToolButton(self.cropping_group)
        QTAThemeSwap().register(
            input_button, "ph.file-arrow-down-light", icon_size=QSize(20, 20)
        )
        input_button.clicked.connect(self._open_script_file_dialogue)

        self.text_box = DNDCodeEditor(
            line_numbers=True,
            wrap_text=False,
            mono_font=True,
            pop_out_expansion=True,
            parent=self.cropping_group,
        )
        self.text_box.setReadOnly(True)
        self.text_box.set_extensions((".vpy", ".avs", ".txt"))
        self.text_box.setFrameShape(QFrame.Shape.Box)
        self.text_box.setFrameShadow(QFrame.Shadow.Sunken)
        self.text_box.dropped.connect(self._handle_drop)
        self.text_box.textChanged.connect(self._parse_text_box)
        pattern = re.compile(r"core.std.Crop\(clip,\s(.+)\)|Crop\((.+)\)")
        self.text_box.highlight_keywords([HighlightKeywords(pattern, "#e1401d", True)])

        top_layout = QHBoxLayout()
        top_layout.addWidget(desc_lbl)
        top_layout.addWidget(input_button, alignment=Qt.AlignmentFlag.AlignRight)

        top_crop_lbl = QLabel("Top", self.cropping_group)
        self.top_crop_spinbox = self._build_spinbox(0)

        bottom_crop_lbl = QLabel("Bottom", self.cropping_group)
        self.bottom_crop_spinbox = self._build_spinbox(0)

        left_crop_lbl = QLabel("Left", self.cropping_group)
        self.left_crop_spinbox = self._build_spinbox(0)

        right_crop_lbl = QLabel("Right", self.cropping_group)
        self.right_crop_spinbox = self._build_spinbox(0)

        okay_button = QToolButton(self.cropping_group)
        QTAThemeSwap().register(okay_button, "ph.check-light", icon_size=QSize(20, 20))
        okay_button.clicked.connect(self._okay)

        lower_layout = QHBoxLayout()
        lower_layout.addWidget(top_crop_lbl)
        lower_layout.addWidget(self.top_crop_spinbox)
        lower_layout.addWidget(bottom_crop_lbl)
        lower_layout.addWidget(self.bottom_crop_spinbox)
        lower_layout.addWidget(left_crop_lbl)
        lower_layout.addWidget(self.left_crop_spinbox)
        lower_layout.addWidget(right_crop_lbl)
        lower_layout.addWidget(self.right_crop_spinbox)
        lower_layout.addWidget(
            build_v_line((0, 0, 0, 0)), alignment=Qt.AlignmentFlag.AlignRight
        )
        lower_layout.addWidget(okay_button, alignment=Qt.AlignmentFlag.AlignRight)

        cropping_layout = QVBoxLayout(self.cropping_group)
        cropping_layout.addLayout(top_layout)
        cropping_layout.addWidget(self.text_box, stretch=1)
        cropping_layout.addLayout(lower_layout)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(self.cropping_group)

    def load_script(self, script_path: Path) -> None:
        """Public method to load a script file."""
        if script_path:
            self._read_text_file(script_path)

    @Slot(list)
    def _handle_drop(self, file_data: List[Path]) -> None:
        if file_data:
            self._read_text_file(file_data[0])

    @Slot()
    def _open_script_file_dialogue(self) -> None:
        script_input, _ = QFileDialog.getOpenFileName(
            caption="Open Encode Script", filter="*.vpy *.avs *.txt"
        )
        if script_input:
            self._read_text_file(Path(script_input))

    def _read_text_file(self, file_path: Path) -> None:
        with open(file_path, "r", encoding="utf-8") as text_file:
            data = text_file.read()
            self.text_box.clear()
            if data:
                self.text_box.setPlainText(data)

    @Slot()
    def _parse_text_box(self) -> None:
        get_text = self.text_box.toPlainText().strip()
        if get_text:
            self.parsed_script = ScriptParser(get_text).get_data()
            crop_values = self.parsed_script.crop_values
            if crop_values:
                self._update_values(*crop_values)

    def _update_values(self, top: int, bottom: int, left: int, right: int) -> None:
        self.top_crop_spinbox.setValue(top)
        self.bottom_crop_spinbox.setValue(bottom)
        self.left_crop_spinbox.setValue(left)
        self.right_crop_spinbox.setValue(right)

    @Slot()
    def _okay(self) -> None:
        """Apply user updates to the ScriptValues with the user input and emit the signal on close"""
        if not self.parsed_script:
            self.parsed_script = ScriptValues()
        self.parsed_script.crop_values = CropValues(
            self.top_crop_spinbox.value(),
            self.bottom_crop_spinbox.value(),
            self.left_crop_spinbox.value(),
            self.right_crop_spinbox.value(),
        )
        self._reset()
        self.crop_confirmed.emit(self.parsed_script)

    def _reset(self) -> None:
        self.text_box.clear()
        for spinbox in (
            self.top_crop_spinbox,
            self.bottom_crop_spinbox,
            self.left_crop_spinbox,
            self.right_crop_spinbox,
        ):
            spinbox.setValue(0)

    def _build_spinbox(self, value: int = 0) -> QSpinBox:
        spinbox = QSpinBox(
            parent=self.cropping_group,
            minimum=-12000,
            maximum=12000,
            singleStep=2,
            value=value,
        )
        spinbox.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Maximum
        )
        return spinbox


class CropWidgetDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        self.setWindowTitle("Crop")
        self.setObjectName("cropWidgetDialog")
        set_top_parent_geometry(self)

        self._result: ScriptValues | None = None

        self.crop_widget = CropWidget(self)
        self.crop_widget.crop_confirmed.connect(self._on_crop_confirmed)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addWidget(self.crop_widget)

    def load_script(self, script_path: Path) -> None:
        if script_path:
            self.crop_widget.load_script(script_path)

    @Slot(ScriptValues)
    def _on_crop_confirmed(self, script_values: ScriptValues) -> None:
        self._result = script_values
        self.accept()

    def exec_crop(self) -> ScriptValues | None:
        """Show dialog modally and return confirmed ScriptValues or None."""
        result = self.exec()
        if result == QDialog.DialogCode.Accepted:
            return self._result
