from pathlib import Path
import platform
from typing import Any

from PySide6.QtCore import QSize, Qt, Slot
from PySide6.QtWidgets import (
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

from src.frontend.custom_widgets.dnd_factory import (
    DNDButton,
    DNDLineEdit,
    DNDToolButton,
)
from src.frontend.stacked_windows.settings.base import BaseSettings
from src.frontend.utils import build_h_line
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap


class DependencySettings(BaseSettings):
    def __init__(self, config, main_window, parent) -> None:
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

        self.add_layout(self._build_dependency_layout(*self.ffmpeg_widgets))
        self.add_layout(self._build_dependency_layout(*self.ffprobe_widgets))
        self.add_layout(self._build_dependency_layout(*self.frame_forge_widgets))
        self.add_layout(self._build_dependency_layout(*self.mkbrr_widgets))
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
        ffmpeg_path = self.config.cfg_payload.ffmpeg
        self.ffmpeg_widgets[2].setText(str(ffmpeg_path) if ffmpeg_path else "")

        ffprobe_path = self.config.cfg_payload.ffprobe
        self.ffprobe_widgets[2].setText(str(ffprobe_path) if ffprobe_path else "")

        frame_forge_path = self.config.cfg_payload.frame_forge
        self.frame_forge_widgets[2].setText(
            str(frame_forge_path) if frame_forge_path else ""
        )

        mkbrr_path = self.config.cfg_payload.mkbrr
        self.mkbrr_widgets[2].setText(str(mkbrr_path) if mkbrr_path else "")

    @Slot()
    def _save_settings(self) -> None:
        ffmpeg_path = self.ffmpeg_widgets[2].text().strip()
        self.config.cfg_payload.ffmpeg = Path(ffmpeg_path) if ffmpeg_path else None

        ffprobe_path = self.ffprobe_widgets[2].text().strip()
        self.config.cfg_payload.ffprobe = Path(ffprobe_path) if ffprobe_path else None

        frame_forge_path = self.frame_forge_widgets[2].text().strip()
        self.config.cfg_payload.frame_forge = (
            Path(frame_forge_path) if frame_forge_path else None
        )

        mkbrr_path = self.mkbrr_widgets[2].text().strip()
        self.config.cfg_payload.mkbrr = Path(mkbrr_path) if mkbrr_path else None
        self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self.ffmpeg_widgets[2].clear()
        self.ffprobe_widgets[2].clear()
        self.frame_forge_widgets[2].clear()
        self.mkbrr_widgets[2].clear()

    @staticmethod
    def _build_dependency_layout(
        lbl_widget: QWidget,
        btn: DNDToolButton | DNDButton,
        entry: QLineEdit,
    ) -> QLayout:
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.addWidget(btn)
        h_layout.addWidget(entry, stretch=10)

        v_layout = QVBoxLayout()
        v_layout.addWidget(lbl_widget)
        v_layout.addLayout(h_layout)
        v_layout.addWidget(build_h_line((0, 1, 0, 1)))
        v_layout.addSpacerItem(
            QSpacerItem(20, 6, QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        )

        return v_layout
