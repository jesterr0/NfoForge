from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSplitter, QSplitterHandle, QWidget
from typing_extensions import override


class CustomSplitterHandle(QSplitterHandle):
    """Custom splitter handle with better visual appearance"""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self.setMinimumSize(12, 12)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        """Custom paint event for a nicer handle appearance"""
        painter = QPainter()
        if not painter.begin(self):
            return

        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # get palette colors for theme awareness
            palette = self.palette()

            # draw grip dots
            dot_color = palette.color(palette.ColorRole.Mid)
            painter.setPen(QPen(dot_color, 1))
            painter.setBrush(dot_color)

            # calculate center and draw dots oriented to the splitter
            center_x = self.width() // 2
            center_y = self.height() // 2
            dot_size = 2
            dot_spacing = 6

            # A horizontal handle gets a horizontal row; a vertical handle gets
            # a vertical row. The explicit painter lifetime prevents Qt from
            # reaching the backing store with an unfinished painter when a
            # splitter is being resized or re-parented.
            if self.width() > self.height():
                for i in range(-2, 3):
                    x = center_x + (i * dot_spacing)
                    painter.drawEllipse(
                        x - dot_size // 2,
                        center_y - dot_size // 2,
                        dot_size,
                        dot_size,
                    )
            # vertical
            else:
                for i in range(-2, 3):
                    y = center_y + (i * dot_spacing)
                    painter.drawEllipse(
                        center_x - dot_size // 2,
                        y - dot_size // 2,
                        dot_size,
                        dot_size,
                    )
        finally:
            painter.end()


class CustomSplitter(QSplitter):
    """Custom splitter with enhanced handle"""

    def __init__(
        self, orientation: Qt.Orientation, parent: QWidget | None = None
    ) -> None:
        super().__init__(orientation=orientation, parent=parent)
        self.setHandleWidth(12)
        self.setChildrenCollapsible(False)

    @override
    def createHandle(self) -> CustomSplitterHandle:
        """Override to return our custom handle"""
        return CustomSplitterHandle(self.orientation(), self)
