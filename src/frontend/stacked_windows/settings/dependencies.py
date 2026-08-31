from pathlib import Path
import platform
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSize, Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QSizePolicy,
    QSpacerItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qtawesome import IconWidget

from src.config.config import ConfigManager
from src.frontend.custom_widgets.dnd_factory import (
    DNDButton,
    DNDLineEdit,
    DNDToolButton,
)
from src.frontend.stacked_windows.settings.base import BaseSettings
from src.frontend.utils import build_h_line
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap

if TYPE_CHECKING:
    from src.frontend.stacked_windows.settings.settings import Settings
    from src.frontend.windows.main_window import MainWindow


class DependencySettings(BaseSettings):
    def __init__(
        self, config: ConfigManager, main_window: "MainWindow", parent: "Settings"
    ) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("dependencySettings")

        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)
        extension = "*.exe" if platform.system() == "Windows" else "*"
        self.ffmpeg_widgets = self._create_dependency_widgets(
            "FFMPEG",
            extension,
            "FFMPEG Path",
            "Required for basic/basic comparison image generation",
        )
        self.ffprobe_widgets = self._create_dependency_widgets(
            "FFPROBE",
            extension,
            "FFPROBE Path",
            "Not required, but useful for plugins if needed",
        )
        self.frame_forge_widgets = self._create_dependency_widgets(
            "FrameForge",
            extension,
            "FrameForge Path",
            "Required for advanced comparison image generation",
        )
        self.mkbrr_widgets = self._create_dependency_widgets(
            "mkbrr",
            extension,
            "mkbrr Path",
            "Not required, but if detected/enabled torrent generation will be done with this",
        )
        self.enable_mkbrr = QCheckBox("Enable mkbrr", self)
        self.enable_mkbrr.setToolTip(
            "If mkbrr is detected torrent generation will be "
            "completed by mkbrr\n(will fall back to torf if failure is detected)"
        )

        self.add_layout(self._build_dependency_layout(*self.ffmpeg_widgets))
        self.add_layout(self._build_dependency_layout(*self.ffprobe_widgets))
        self.add_layout(self._build_dependency_layout(*self.frame_forge_widgets))
        self.add_layout(
            self._build_dependency_layout(
                *self.mkbrr_widgets, extra_widget=self.enable_mkbrr
            )
        )
        self.add_layout(self.reset_layout, add_stretch=True)

        self._load_saved_settings()

    def _create_dependency_widgets(
        self, label_text: str, ext_filter: str, dialog_title: str, tooltip: str
    ) -> tuple[QWidget, Any, DNDLineEdit]:
        """Helper to create label, button, entry and clear button dependencies."""
        label = QLabel(label_text, self)
        label.setToolTip(f"Sets the path to {label_text}")
        information = IconWidget()
        information.setCursor(Qt.CursorShape.WhatsThisCursor)
        information.setToolTip(tooltip)
        QTAThemeSwap().register(
            information,
            "ph.info-light",
            icon_size=QSize(20, 20),
        )
        lbl_widget = QWidget()
        lbl_layout = QHBoxLayout(lbl_widget)
        lbl_layout.setContentsMargins(0, 0, 0, 0)
        lbl_layout.addWidget(label)
        lbl_layout.addStretch()
        lbl_layout.addWidget(information)

        entry = DNDLineEdit(self)
        entry.setToolTip(f"Sets the path to {label_text} via drag and drop")
        entry.setReadOnly(True)
        entry.set_extensions(("*",))
        entry.dropped.connect(lambda e: self._update_entry(entry, e))

        browse_button = QToolButton(self)
        QTAThemeSwap().register(
            browse_button, "ph.file-arrow-down-light", icon_size=QSize(24, 24)
        )
        browse_button.setToolTip(f"Set path to {label_text}")
        browse_button.clicked.connect(
            lambda: self._file_dialogue(
                entry, dialog_title, f"{label_text} ({ext_filter});;All Files (*)"
            )
        )

        return lbl_widget, browse_button, entry

    def _file_dialogue(self, widget: QLineEdit, caption: str, file_filter: str) -> None:
        input_file, _ = QFileDialog.getOpenFileName(caption=caption, filter=file_filter)
        if input_file:
            widget.setText(str(Path(input_file)))

    @Slot(list)
    def _update_entry(self, widget: QLineEdit, drop_event: list[Path]) -> None:
        if drop_event:
            widget.setText(str(drop_event[0]))

    @Slot()
    def _clear_entry(self, widget: QLineEdit) -> None:
        widget.clear()

    @Slot()
    def _load_saved_settings(self) -> None:
        """Applies user saved settings from the config"""
        ffmpeg_path = self.config.settings.dependencies.ffmpeg
        self.ffmpeg_widgets[2].setText(str(ffmpeg_path) if ffmpeg_path else "")

        ffprobe_path = self.config.settings.dependencies.ffprobe
        self.ffprobe_widgets[2].setText(str(ffprobe_path) if ffprobe_path else "")

        frame_forge_path = self.config.settings.dependencies.frame_forge
        self.frame_forge_widgets[2].setText(
            str(frame_forge_path) if frame_forge_path else ""
        )

        mkbrr_path = self.config.settings.dependencies.mkbrr
        self.mkbrr_widgets[2].setText(str(mkbrr_path) if mkbrr_path else "")
        self.enable_mkbrr.setChecked(self.config.settings.dependencies.enable_mkbrr)

    @staticmethod
    def _pending_path(entry: QLineEdit) -> Path | None:
        value = entry.text().strip()
        return Path(value) if value else None

    @property
    def pending_ffmpeg_path(self) -> Path | None:
        return self._pending_path(self.ffmpeg_widgets[2])

    @property
    def pending_frame_forge_path(self) -> Path | None:
        return self._pending_path(self.frame_forge_widgets[2])

    @Slot()
    def _save_settings(self) -> None:
        self.config.settings.dependencies.ffmpeg = self.pending_ffmpeg_path

        self.config.settings.dependencies.ffprobe = self._pending_path(
            self.ffprobe_widgets[2]
        )

        self.config.settings.dependencies.frame_forge = self.pending_frame_forge_path

        self.config.settings.dependencies.mkbrr = self._pending_path(
            self.mkbrr_widgets[2]
        )
        self.config.settings.dependencies.enable_mkbrr = self.enable_mkbrr.isChecked()
        self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self.ffmpeg_widgets[2].clear()
        self.ffprobe_widgets[2].clear()
        self.frame_forge_widgets[2].clear()
        self.mkbrr_widgets[2].clear()
        self.enable_mkbrr.setChecked(self.config.defaults.dependencies.enable_mkbrr)

    @staticmethod
    def _build_dependency_layout(
        lbl_widget: QWidget,
        btn: DNDToolButton | DNDButton,
        entry: QLineEdit,
        extra_widget: QWidget | None = None,
    ) -> QLayout:
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.addWidget(btn)
        h_layout.addWidget(entry, stretch=10)

        v_layout = QVBoxLayout()
        v_layout.addWidget(lbl_widget)
        v_layout.addLayout(h_layout)
        if extra_widget is not None:
            v_layout.addWidget(extra_widget)
        v_layout.addWidget(build_h_line((0, 1, 0, 1)))
        v_layout.addSpacerItem(
            QSpacerItem(20, 6, QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        )

        return v_layout
