from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QSplitter, QSplitterHandle
from typing_extensions import override


class CustomSplitterHandle(QSplitterHandle):
    """Custom splitter handle with better visual appearance"""

    def __init__(self, orientation, parent) -> None:
        super().__init__(orientation, parent)
        self.setMinimumSize(12, 12)

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

        # calculate center and draw dots oriented to the splitter
        center_x = self.width() // 2
        center_y = self.height() // 2
        dot_size = 2
        dot_spacing = 6

        # draw 5 dots; orientation-aware: decide orientation from the handle geometry
        # If the handle is wider than tall it's a horizontal handle (draw row), otherwise
        # draw a vertical column of dots.
        if self.width() > self.height():
            # horizontal handle -> draw horizontally aligned dots
            for i in range(-2, 3):
                x = center_x + (i * dot_spacing)
                painter.drawEllipse(
                    x - dot_size // 2, center_y - dot_size // 2, dot_size, dot_size
                )
        else:
            # vertical handle -> draw vertically stacked dots
            for i in range(-2, 3):
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
