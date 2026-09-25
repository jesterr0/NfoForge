from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QImage, QPainter, QPaintEvent, QTransform
from PySide6.QtWidgets import QApplication, QWidget


class ImageLabel(QWidget):
    """Custom widget for displaying images with scaling."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        preferred_size: QSize | None = None,
        minimum_size_hint: QSize | None = None,
    ) -> None:
        """Initialize the ImageLabel widget."""
        super().__init__(parent)
        self._image: QImage | None = None
        self._preferred_size = (
            QSize(preferred_size) if preferred_size is not None else None
        )
        self._minimum_size_hint = (
            QSize(minimum_size_hint) if minimum_size_hint is not None else None
        )

    def sizeHint(self) -> QSize:
        """Return the preferred display size supplied by the caller."""
        if self._preferred_size is not None:
            return QSize(self._preferred_size)
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        """Return the caller's minimum display size, when configured."""
        if self._minimum_size_hint is not None:
            return QSize(self._minimum_size_hint)
        return super().minimumSizeHint()

    def setImage(self, image: QImage) -> None:
        """Set the image to be displayed."""
        self._image = image
        self.update()

    def clearImage(self) -> None:
        """Clear the currently displayed image."""
        self._image = None
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Handle the paint event to draw the image."""
        if self._image is None or self._image.isNull():
            return

        # Calculate the scaling factor to fit the image within the widget
        painter = QPainter()
        if not painter.begin(self):
            return

        try:
            width = self.width()
            height = self.height()
            image_width = self._image.width()
            image_height = self._image.height()
            if width <= 0 or height <= 0 or image_width <= 0 or image_height <= 0:
                return

            r1 = width / image_width
            r2 = height / image_height
            r = min(r1, r2)
            x = (width - image_width * r) / 2
            y = (height - image_height * r) / 2

            # Transform and draw the image
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setTransform(QTransform().translate(x, y).scale(r, r))
            painter.drawImage(QPointF(0, 0), self._image)
        finally:
            painter.end()


if __name__ == "__main__":
    app = QApplication([])
    label = ImageLabel()
    label.setImage(QImage(r"filename.png"))
    label.show()
    app.exec()
