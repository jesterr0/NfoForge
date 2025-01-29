from PySide6.QtWidgets import (
    QSpacerItem,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QWidget,
)
from PySide6.QtCore import Slot
from PySide6.QtGui import QWheelEvent

from src.enums.url_type import URLType
from src.frontend.custom_widgets.basic_code_editor import CodeEditor


class URLOrganizer(QWidget):
    FAKE_IMG_URLS = [
        f"https://fakeimage.com/img/{str(i).zfill(2)}.png" for i in range(1, 13)
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("urlOrganizer")

        self.url_type = URLType.BBCODE

        # control Widgets
        self.column_count_lbl = QLabel("Columns", self)
        self.column_count_spinbox = QSpinBox(self)
        self.column_count_spinbox.wheelEvent = self._ignore_wheel_event
        self.column_count_spinbox.setRange(1, 4)
        self.column_count_spinbox.valueChanged.connect(self.update_example)
        self.column_count_layout = self._build_v_layout(
            self.column_count_lbl, self.column_count_spinbox, (0, 0, 0, 0)
        )

        self.column_space_lbl = QLabel("Column Space", self)
        self.column_space_spinbox = QSpinBox(self)
        self.column_space_spinbox.wheelEvent = self._ignore_wheel_event
        self.column_space_spinbox.setRange(1, 10)
        self.column_space_spinbox.valueChanged.connect(self.update_example)
        self.column_space_layout = self._build_v_layout(
            self.column_space_lbl, self.column_space_spinbox, (0, 0, 0, 0)
        )

        self.row_space_lbl = QLabel("Row Space", self)
        self.row_space_spinbox = QSpinBox(self)
        self.row_space_spinbox.wheelEvent = self._ignore_wheel_event
        self.row_space_spinbox.setRange(0, 10)
        self.row_space_spinbox.valueChanged.connect(self.update_example)
        self.row_space_layout = self._build_v_layout(
            self.row_space_lbl, self.row_space_spinbox, (0, 0, 0, 0)
        )

        # example output section
        self.example_box_label = QLabel("Example Output", self)
        self.example_box = CodeEditor(
            line_numbers=False, wrap_text=False, mono_font=True, parent=self
        )
        self.example_box.setReadOnly(True)

        # layouts
        self.format_control_box = QHBoxLayout()
        self.format_control_box.setContentsMargins(0, 0, 0, 0)
        self.format_control_box.addLayout(self.column_count_layout)
        self.format_control_box.addLayout(self.column_space_layout)
        self.format_control_box.addLayout(self.row_space_layout)

        self.example_layout = QVBoxLayout()
        self.example_layout.addWidget(self.example_box_label)
        self.example_layout.addWidget(self.example_box)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addLayout(self.format_control_box)
        self.main_layout.addLayout(self.example_layout)
        self.main_layout.addSpacerItem(
            QSpacerItem(
                1, 1, QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding
            )
        )

    def load_settings(
        self, url_type: URLType, columns: int, col_space: int, row_space: int
    ) -> None:
        widgets = (
            self.column_count_spinbox,
            self.column_space_spinbox,
            self.row_space_spinbox,
        )
        for widget in widgets:
            widget.blockSignals(True)
        self.url_type = url_type
        self.column_count_spinbox.setValue(columns)
        self.column_space_spinbox.setValue(col_space)
        self.row_space_spinbox.setValue(row_space)
        for widget in widgets:
            widget.blockSignals(False)
        self.update_example()

    def current_settings(self) -> tuple[int, int, int]:
        """Returns a tuple(columns: int, col_space: int, row_space: int)"""
        return (
            self.column_count_spinbox.value(),
            self.column_space_spinbox.value(),
            self.row_space_spinbox.value(),
        )

    @Slot(int)
    def update_example(self, _: int | None = None) -> None:
        self.example_box.setPlainText(self._format_urls())

    def _format_urls(self) -> str:
        urls = None
        if self.url_type == URLType.BBCODE:
            urls = [f"[img]{x}[/img]" for x in self.FAKE_IMG_URLS]
        elif self.url_type == URLType.HTML:
            urls = [f'<img src="{x}">' for x in self.FAKE_IMG_URLS]
        if not isinstance(urls, list) or not urls:
            raise AttributeError("Invalid URL data")

        columns = self.column_count_spinbox.value()
        column_space = self.column_space_spinbox.value()
        row_space = self.row_space_spinbox.value() + 1

        column_spacing = " " * column_space
        row_spacing = "\n" * row_space

        formatted_rows = []
        for i in range(0, len(urls), columns):
            row = column_spacing.join(urls[i : i + columns])
            formatted_rows.append(row)

        formatted_text = row_spacing.join(formatted_rows)
        return formatted_text

    @staticmethod
    def _build_h_layout(
        widget_1: QWidget, widget_2: QWidget, margins: tuple[int, int, int, int]
    ) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(*margins)
        layout.addWidget(widget_1)
        layout.addWidget(widget_2, stretch=1)
        return layout

    @staticmethod
    def _build_v_layout(
        widget_1: QWidget, widget_2: QWidget, margins: tuple[int, int, int, int]
    ) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(*margins)
        layout.addWidget(widget_1)
        layout.addWidget(widget_2)
        return layout

    @staticmethod
    def _ignore_wheel_event(event: QWheelEvent) -> None:
        event.ignore()
