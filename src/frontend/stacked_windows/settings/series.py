from pathlib import Path
from typing import Union

from PySide6.QtCore import Qt, QSize, Signal, QObject
from PySide6.QtWidgets import (
    QHBoxLayout,
    QWidget,
    QToolButton,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QSpacerItem,
    QScrollBar,
    QScrollArea,
    QFrame,
    QStackedWidget,
    QButtonGroup,
    QStyle,
)
from PySide6.QtGui import QCursor, QIcon

from src.frontend.custom_widgets.combo_box import CustomComboBox


class SeriesSettings(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("seriesSettings")
        self.setFrameShape(QFrame.Shape.Box)
        self.setFrameShadow(QFrame.Shadow.Sunken)
        self.label = QLabel("WIP")

        scroll_area = QScrollArea(self)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        # Allows the widget inside to resize with the scroll area
        scroll_area.setWidgetResizable(True)
        inner_widget = QWidget(scroll_area)
        inner_layout = QVBoxLayout(inner_widget)
        inner_layout.addWidget(self.label)

        scroll_area.setWidget(inner_widget)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll_area)
