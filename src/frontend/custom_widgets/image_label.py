from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtGui import QPainter, QTransform, QImage
from PySide6.QtCore import QPointF


class ImageLabel(QWidget):
    """Custom widget for displaying images with scaling."""

    def __init__(self, parent=None):
        """Initialize the ImageLabel widget."""
        super().__init__(parent)
        self._image = None

    def setImage(self, image):
        """Set the image to be displayed."""
        self._image = image
        self.update()

    def clearImage(self):
        """Clear the currently displayed image."""
        self._image = None
        self.update()

    def paintEvent(self, event):
        """Handle the paint event to draw the image."""
        if self._image is None or self._image.isNull():
            return

        # Calculate the scaling factor to fit the image within the widget
        painter = QPainter(self)
        width = self.width()
        height = self.height()
        imageWidth = self._image.width()
        imageHeight = self._image.height()
        r1 = width / imageWidth
        r2 = height / imageHeight
        r = min(r1, r2)
        x = (width - imageWidth * r) / 2
        y = (height - imageHeight * r) / 2

        # Transform and draw the image
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setTransform(QTransform().translate(x, y).scale(r, r))
        painter.drawImage(QPointF(0, 0), self._image)


if __name__ == "__main__":
    app = QApplication([])
    label = ImageLabel()
    label.setImage(QImage(r"filename.png"))
    label.show()
    app.exec()
