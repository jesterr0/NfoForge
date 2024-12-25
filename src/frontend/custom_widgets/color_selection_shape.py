from PySide6.QtCore import QSize, Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPaintEvent, QPainter, QPainterPath, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QWidget,
    QVBoxLayout,
    QPushButton,
)


class ColorSelectionShape(QWidget):
    PADDING = 2
    SQUARE_CORNER_VALUE = 0.2

    color_changed = Signal(object)  # QColor

    def __init__(
        self,
        width: int = 20,
        height: int = 20,
        initial_color: QColor = QColor("white"),
        enable_alpha: bool = False,
        circle: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.current_color = initial_color
        self.setFixedSize(QSize(width, height))
        self.enable_alpha = enable_alpha
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        if circle:
            self.paintEvent = self.circlePaintEvent
        else:
            self.paintEvent = self.squaredPaintEvent

    def circlePaintEvent(self, event: QPaintEvent) -> None:
        """Draw the circle with the current color."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        widget_rect = self.rect()
        size = min(widget_rect.width(), widget_rect.height()) - 2 * self.PADDING
        circle = QRectF(
            widget_rect.left() + self.PADDING,
            widget_rect.top() + self.PADDING,
            size,
            size,
        )
        path.addEllipse(circle)
        painter.fillPath(path, self.current_color)
        painter.end()

    def squaredPaintEvent(self, event: QPaintEvent) -> None:
        """Draw the square with rounded corners and the current color."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect_size = min(self.width(), self.height()) - 2 * self.PADDING
        rounded_rect = QRectF(self.PADDING, self.PADDING, rect_size, rect_size)

        corner_radius = rect_size * self.SQUARE_CORNER_VALUE
        path = QPainterPath()
        path.addRoundedRect(rounded_rect, corner_radius, corner_radius)

        painter.fillPath(path, self.current_color)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse click to open a color picker."""
        if event.button() == Qt.MouseButton.LeftButton:
            color_picker = QColorDialog(self.current_color, self)
            if self.enable_alpha:
                color_picker.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel)
            color_picker.exec()
            new_color = color_picker.currentColor()
            if new_color.isValid():
                self.current_color = new_color
                self.color_changed.emit(self.current_color)
                self.update()

    def get_color(self) -> QColor:
        """Returns current selected color as a QColor object."""
        return self.current_color

    def get_hex_color(self) -> str:
        """Returns current selected hex color format in HexRgb or HexArgb depending if alpha was included or not."""
        return self.current_color.name(
            QColor.NameFormat.HexArgb if self.enable_alpha else QColor.NameFormat.HexRgb
        )

    def update_color(self, color: QColor) -> None:
        """Updates the color of the widget as needed."""
        self.current_color = color
        self.update()


if __name__ == "__main__":
    app = QApplication([])

    class MainWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Color Circle Example")
            self.setLayout(QVBoxLayout())

            # create a color circle and add it to the layout
            self.color_circle = ColorSelectionShape(
                initial_color=QColor("blue"), circle=True
            )
            self.layout().addWidget(self.color_circle)

            # add a button to demonstrate other UI elements
            self.test_button = QPushButton("Click Me!")
            self.layout().addWidget(self.test_button)

    main_window = MainWindow()
    main_window.show()

    app.exec()
