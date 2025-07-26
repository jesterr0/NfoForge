from pathlib import Path
import re
from typing import List

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtWidgets import (
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

from src.backend.utils.crop_detect import parse_scripts
from src.frontend.custom_widgets.basic_code_editor import HighlightKeywords
from src.frontend.custom_widgets.dnd_factory import DNDCustomLineEdit
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from src.packages.custom_types import CropValues


class CropWidget(QWidget):
    crop_confirmed = Signal(CropValues)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        cropping_group = QGroupBox("Crop")

        input_button = QToolButton(self)
        QTAThemeSwap().register(
            input_button, "ph.file-arrow-down-light", icon_size=QSize(24, 24)
        )
        input_button.clicked.connect(self._open_script_file_dialogue)

        self.text_box = DNDCustomLineEdit(
            line_numbers=True, wrap_text=False, mono_font=True, parent=self
        )
        self.text_box.set_extensions((".vpy", ".avs"))
        self.text_box.setPlaceholderText(
            "Open AviSynth or VapourSynth scripts to detect crop automatically"
        )
        self.text_box.setFrameShape(QFrame.Shape.Box)
        self.text_box.setFrameShadow(QFrame.Shadow.Sunken)
        self.text_box.dropped.connect(self._handle_drop)
        self.text_box.textChanged.connect(self._parse_text_box)

        top_layout = QHBoxLayout()
        top_layout.addWidget(input_button)
        top_layout.addWidget(self.text_box)

        top_crop_lbl = QLabel("Top")
        self.top_crop_spinbox = self._build_spinbox(0)

        bottom_crop_lbl = QLabel("Bottom")
        self.bottom_crop_spinbox = self._build_spinbox(0)

        left_crop_lbl = QLabel("Left")
        self.left_crop_spinbox = self._build_spinbox(0)

        right_crop_lbl = QLabel("Right")
        self.right_crop_spinbox = self._build_spinbox(0)

        middle_layout = QHBoxLayout()
        middle_layout.addWidget(top_crop_lbl)
        middle_layout.addWidget(self.top_crop_spinbox)
        middle_layout.addWidget(bottom_crop_lbl)
        middle_layout.addWidget(self.bottom_crop_spinbox)
        middle_layout.addWidget(left_crop_lbl)
        middle_layout.addWidget(self.left_crop_spinbox)
        middle_layout.addWidget(right_crop_lbl)
        middle_layout.addWidget(self.right_crop_spinbox)

        cropping_layout = QVBoxLayout(cropping_group)
        cropping_layout.addLayout(top_layout)
        cropping_layout.addLayout(middle_layout)

        button_box_layout = QHBoxLayout()
        okay_button = QToolButton(self)
        QTAThemeSwap().register(okay_button, "ph.check-light", icon_size=QSize(24, 24))
        okay_button.clicked.connect(self._okay)
        button_box_layout.addWidget(okay_button, alignment=Qt.AlignmentFlag.AlignRight)
        button_box_layout.setAlignment(Qt.AlignmentFlag.AlignRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(cropping_group)
        layout.addLayout(button_box_layout)

    @Slot(list)
    def _handle_drop(self, file_data: List[Path]) -> None:
        if file_data:
            self._read_text_file(file_data[0])

    @Slot()
    def _open_script_file_dialogue(self) -> None:
        script_input, _ = QFileDialog.getOpenFileName(
            caption="Open Encode Script", filter="*.vpy *.avs"
        )
        if script_input:
            self._read_text_file(Path(script_input))

    def _read_text_file(self, file_path: Path) -> None:
        with open(file_path, "r", encoding="utf-8") as text_file:
            data = text_file.read()
            self.text_box.clear()
            if data:
                self.text_box.setPlainText(data)
                pattern = re.compile(r"core.std.Crop\(clip,\s(.+)\)|Crop\((.+)\)")
                self.text_box.highlight_keywords(
                    [HighlightKeywords(pattern, "#e1401d", True)]
                )

    @Slot()
    def _parse_text_box(self) -> None:
        get_text = self.text_box.toPlainText().strip()
        if get_text:
            self._update_values(*parse_scripts(get_text))

    def _update_values(self, top: int, bottom: int, left: int, right: int) -> None:
        self.top_crop_spinbox.setValue(top)
        self.bottom_crop_spinbox.setValue(bottom)
        self.left_crop_spinbox.setValue(left)
        self.right_crop_spinbox.setValue(right)

    @Slot()
    def _okay(self) -> None:
        crop_values = CropValues(
            self.top_crop_spinbox.value(),
            self.bottom_crop_spinbox.value(),
            self.left_crop_spinbox.value(),
            self.right_crop_spinbox.value(),
        )
        self._reset()
        self.crop_confirmed.emit(crop_values)

    def _reset(self) -> None:
        self.text_box.clear()
        for spinbox in (
            self.top_crop_spinbox,
            self.bottom_crop_spinbox,
            self.left_crop_spinbox,
            self.right_crop_spinbox,
        ):
            spinbox.setValue(0)

    @staticmethod
    def _build_spinbox(value: int = 0) -> QSpinBox:
        spinbox = QSpinBox()
        spinbox.setRange(-12000, 12000)
        spinbox.setSingleStep(2)
        spinbox.setValue(value)
        spinbox.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Maximum
        )
        return spinbox
