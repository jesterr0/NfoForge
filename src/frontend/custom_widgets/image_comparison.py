from os import PathLike
from pathlib import Path
from typing import Union

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.frontend.custom_widgets.image_label import ImageLabel
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap


class SideBySideImage(QWidget):
    offset_applied = Signal((int,))

    def __init__(self, sync_dir: Union[str, PathLike], parent=None):
        super().__init__(parent)

        # vars
        self.sync_dir = Path(sync_dir)
        self.ref_index = 0
        self.reference_img = sorted(
            self.sync_dir.glob("*.png"), key=lambda x: int(x.stem.split("__")[1])
        )
        self.ref_img_1 = QPixmap(self.reference_img[self.ref_index])

        self.sync_dirs = [
            sorted(Path(self.sync_dir / "sync1").glob("*.png")),
            sorted(Path(self.sync_dir / "sync2").glob("*.png")),
        ]
        self.sync_dir = self.sync_dirs[self.ref_index]
        self.sync_dir_len = len(self.sync_dir)

        self.sync_img_index = 0
        self.sync_img = QPixmap(self.sync_dir[self.sync_img_index])

        # ui
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 10000)
        self.slider.setValue(5000)
        self.slider.valueChanged.connect(self.updateImage)

        # Display combined image in QLabel
        self.label = ImageLabel()
        self.updateImage()

        # buttons
        self.swap_reference = QToolButton(self)
        QTAThemeSwap().register(
            self.swap_reference, "ph.swap-light", icon_size=QSize(24, 24)
        )
        self.swap_reference.setToolTip("Swap reference frames")
        self.swap_reference.clicked.connect(self.swap_ref)

        self.next_frame_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.next_frame_btn, "ph.arrow-right-light", icon_size=QSize(24, 24)
        )
        self.next_frame_btn.clicked.connect(lambda: self.change_frame(1))

        self.prev_frame_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.prev_frame_btn, "ph.arrow-left-light", icon_size=QSize(24, 24)
        )
        self.prev_frame_btn.clicked.connect(lambda: self.change_frame(-1))

        self.apply_offset = QToolButton(self)
        QTAThemeSwap().register(
            self.apply_offset, "ph.check-light", icon_size=QSize(24, 24)
        )
        self.apply_offset.setToolTip("Apply offset")
        self.apply_offset.clicked.connect(self.send_offset)

        button_layout = QHBoxLayout()
        button_layout.addWidget(
            self.swap_reference, alignment=Qt.AlignmentFlag.AlignLeft
        )
        button_layout.addWidget(
            self.prev_frame_btn, alignment=Qt.AlignmentFlag.AlignRight
        )
        button_layout.addWidget(
            self.next_frame_btn, alignment=Qt.AlignmentFlag.AlignLeft
        )
        button_layout.addWidget(
            self.apply_offset, alignment=Qt.AlignmentFlag.AlignRight
        )

        # Create layout and add label and slider
        layout = QVBoxLayout(self)
        layout.addWidget(self.label, stretch=10)
        layout.addWidget(self.slider, stretch=1)
        layout.addLayout(button_layout, stretch=1)
        self.setLayout(layout)

    def send_offset(self):
        reference_frame_num = int(
            self.reference_img[self.ref_index].stem.split("__")[1]
        )
        offset_frame_num = int(self.sync_dir[self.sync_img_index].stem.split("__")[1])
        self.offset_applied.emit(offset_frame_num - reference_frame_num)

    def swap_ref(self):
        if self.ref_index == 0:
            self.ref_index = 1
        elif self.ref_index == 1:
            self.ref_index = 0

        self.ref_img_1 = QPixmap(self.reference_img[self.ref_index])
        self.sync_dir = self.sync_dirs[self.ref_index]
        self.sync_dir_len = len(self.sync_dir)
        self.sync_img_index = 0
        self.sync_img = QPixmap(self.sync_dir[self.sync_img_index])
        self.slider.setValue(5000)
        self.updateImage()

    def change_frame(self, direction):
        new_index = self.sync_img_index + direction
        if 0 <= new_index < self.sync_dir_len:
            self.sync_img_index = new_index
            self.sync_img = QPixmap(self.sync_dir[self.sync_img_index])
            self.updateImage()

    def updateImage(self):
        blend_factor = self.slider.value() / 10000.0

        # Calculate the width for each image
        image1_width = int(self.ref_img_1.width() * blend_factor)
        image2_width = self.ref_img_1.width() - image1_width

        # Create a new pixmap for combined image
        combined_image = QPixmap(self.ref_img_1.size())

        # Fill pixmap with first image
        combined_image.fill(Qt.transparent)
        painter = QPainter(combined_image)
        painter.drawPixmap(
            0, 0, self.ref_img_1.copy(0, 0, image1_width, self.ref_img_1.height())
        )

        # Fill the remaining area with second image
        painter.drawPixmap(
            image1_width,
            0,
            self.sync_img.copy(
                self.sync_img.width() - image2_width,
                0,
                image2_width,
                self.sync_img.height(),
            ),
        )

        # Draw a vertical line to separate the images
        pen = QPen(Qt.red, 2, Qt.SolidLine)
        painter.setPen(pen)

        x = image1_width
        painter.drawLine(x, 0, x, combined_image.height())
        painter.end()

        # Update QLabel with combined image
        q_img = combined_image.toImage()
        self.label.setImage(q_img)


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = SideBySideImage(r"input")
    window.show()
    sys.exit(app.exec())
