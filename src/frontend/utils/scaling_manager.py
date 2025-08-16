from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QWidget


class FontScalingManager(QObject):
    scaling_changed = Signal(float)
    scaling_changed_by_user = Signal(float)

    def __init__(self, initial_scale_factor: float = 1.0, parent=None):
        super().__init__(parent)
        self._scale_factor = initial_scale_factor
        self._base_font_size = 12
        self._min_scale = 0.5
        self._max_scale = 3.0
        self._scale_step = 0.1

    def setup_shortcuts(self, widget: QWidget):
        """Setup keyboard shortcuts for font scaling."""
        zoom_in_action = QAction("Font Zoom In", widget)
        zoom_in_action.setShortcut(QKeySequence("Ctrl++"))
        zoom_in_action.triggered.connect(self.zoom_in)
        widget.addAction(zoom_in_action)

        zoom_in_alt_action = QAction("Font Zoom In Alt", widget)
        zoom_in_alt_action.setShortcut(QKeySequence("Ctrl+="))
        zoom_in_alt_action.triggered.connect(self.zoom_in)
        widget.addAction(zoom_in_alt_action)

        zoom_out_action = QAction("Font Zoom Out", widget)
        zoom_out_action.setShortcut(QKeySequence("Ctrl+-"))
        zoom_out_action.triggered.connect(self.zoom_out)
        widget.addAction(zoom_out_action)

        zoom_reset_action = QAction("Font Reset Zoom", widget)
        zoom_reset_action.setShortcut(QKeySequence("Ctrl+0"))
        zoom_reset_action.triggered.connect(self.reset_zoom)
        widget.addAction(zoom_reset_action)

        # apply initial scaling
        if self._scale_factor != 1.0:
            self._apply_font_scaling()

    def zoom_in(self):
        """Increase font scaling."""
        new_scale = min(self._scale_factor + self._scale_step, self._max_scale)
        self.set_scale_factor(new_scale, user_initiated=True)

    def zoom_out(self):
        """Decrease font scaling."""
        new_scale = max(self._scale_factor - self._scale_step, self._min_scale)
        self.set_scale_factor(new_scale, user_initiated=True)

    def reset_zoom(self):
        """Reset font scaling to 100%."""
        self.set_scale_factor(1.0, user_initiated=True)

    def set_scale_factor(self, scale_factor: float, user_initiated: bool = False):
        """Set the font scale factor."""
        if scale_factor == self._scale_factor:
            return

        self._scale_factor = max(self._min_scale, min(scale_factor, self._max_scale))
        self._apply_font_scaling()

        # always emit the general scaling_changed signal
        self.scaling_changed.emit(self._scale_factor)

        # only emit scaling_changed_by_user for user-initiated changes (hotkeys)
        if user_initiated:
            self.scaling_changed_by_user.emit(self._scale_factor)

    def get_scale_factor(self) -> float:
        """Get the current font scale factor."""
        return self._scale_factor

    def _apply_font_scaling(self):
        """Apply font scaling to the application."""
        app = QApplication.instance()
        if app and isinstance(app, QApplication):
            font = app.font()
            new_size = int(self._base_font_size * self._scale_factor)
            font.setPixelSize(new_size)
            app.setFont(font)
