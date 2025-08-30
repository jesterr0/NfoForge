from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QSplitter, QSplitterHandle
from typing_extensions import override


class CustomSplitterHandle(QSplitterHandle):
    """Custom splitter handle with better visual appearance"""

    def __init__(self, orientation, parent) -> None:
        super().__init__(orientation, parent)
        self.setMinimumWidth(12)

    @override
    def paintEvent(self, event) -> None:
        """Custom paint event for a nicer handle appearance"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # get palette colors for theme awareness
        palette = self.palette()

        # background - use button color from palette (we could modify the background but looks cleaner without)
        # bg_color = palette.color(palette.ColorRole.Button)
        # painter.fillRect(self.rect(), bg_color)

        # draw grip dots
        dot_color = palette.color(palette.ColorRole.Mid)
        painter.setPen(QPen(dot_color, 1))
        painter.setBrush(dot_color)

        # calculate center and draw 3 dots vertically
        center_x = self.width() // 2
        center_y = self.height() // 2
        dot_size = 2
        dot_spacing = 6

        # 5 dots
        for i in range(-1, 4):
            y = center_y + (i * dot_spacing)
            painter.drawEllipse(
                center_x - dot_size // 2, y - dot_size // 2, dot_size, dot_size
            )


class CustomSplitter(QSplitter):
    """Custom splitter with enhanced handle"""

    def __init__(self, orientation, parent=None, *kwargs) -> None:
        super().__init__(orientation=orientation, parent=parent, *kwargs)
        self.setHandleWidth(12)
        self.setChildrenCollapsible(False)

    @override
    def createHandle(self) -> CustomSplitterHandle:
        """Override to return our custom handle"""
        return CustomSplitterHandle(self.orientation(), self)
