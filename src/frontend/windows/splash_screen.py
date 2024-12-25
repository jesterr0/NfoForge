import traceback
from typing import Type

from PySide6.QtWidgets import (
    QFrame,
    QWidget,
    QLabel,
    QVBoxLayout,
    QProgressBar,
)
from PySide6.QtGui import Qt, QPixmap
from PySide6.QtCore import QThread, SignalInstance, Signal, Slot

from src.version import __version__
from src.config.config import Config
from src.backend.utils.working_dir import RUNTIME_DIR
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.plugins.loader import PluginLoader
from src.plugins.plugin_payload import PluginPayload

# "built in" plugins
from src.frontend.wizards.media_input_basic import MediaInputBasic
from src.frontend.wizards.media_input_advanced import MediaInputAdvanced

message_box_frame_style = """\
    QFrame#messageBox {
        background-color: rgba(28, 31, 34, 0.7);
    }
"""

mini_progress_bar_style = """\
    QProgressBar#miniProgressBar {
        border: 0;
        background-color: rgba(28, 31, 34, 0.95);
    }

    QProgressBar#miniProgressBar::chunk {
        background-color: #fb641a;
    }
"""


class SplashScreenLoader(QThread):
    error_message = Signal(str)
    success = Signal()

    def __init__(
        self, config: Config, update_splash_msg: SignalInstance, parent=None
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.update_splash_msg = update_splash_msg

    def run(self) -> None:
        try:
            self.init_plugins()
            self.success.emit()
        except Exception as error:
            self.error_message.emit(
                f"Unhandled error: {error}\n{traceback.format_exc()}"
            )

    def init_plugins(self) -> Type[BaseWizardPage] | None:
        # built in plugins
        self._update_built_in_plugins()

        # load user plugins
        plugin_loader = PluginLoader(self.update_splash_msg)
        plugins = plugin_loader.load_plugins()
        self.config.loaded_plugins.update(plugins)

        # check if we have missing keys and remove them from the running config
        plugins = self.config.loaded_plugins.keys()
        if self.config.cfg_payload.wizard_page not in plugins:
            self.config.cfg_payload.wizard_page = None
        if self.config.cfg_payload.token_replacer not in plugins:
            self.config.cfg_payload.token_replacer = None
        self.config.save_config()

    def _update_built_in_plugins(self) -> None:
        built_in_plugins = {
            "Basic (built in)": PluginPayload(
                name="Basic (built in)", wizard=MediaInputBasic
            ),
            "Advanced (built in)": PluginPayload(
                name="Advanced (built in)",
                wizard=MediaInputAdvanced,
            ),
            "Token Replacer (disabled)": PluginPayload(
                name="Token Replacer (disabled)",
                token_replacer=False,
            ),
            "Pre Upload (disabled)": PluginPayload(
                name="Pre Upload (disabled)",
                pre_upload=False,
            ),
        }
        self.config.loaded_plugins.update(built_in_plugins)


class SplashScreen(QWidget):
    update_message_box = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.resize(426, 240)
        self.setCursor(Qt.CursorShape.BusyCursor)

        self.update_message_box.connect(self.updateMessageBox)

        # this must be defined first to fill the background
        pixmap = QPixmap(RUNTIME_DIR / "images" / "nfoforge_splash_screen_4.png")
        self.splash_img = QLabel(self)
        self.splash_img.setPixmap(pixmap)
        self.splash_img.setScaledContents(True)

        # labels
        version_lbl = QLabel(f"v{__version__}", self)
        version_lbl.setStyleSheet("color: #D3D3D3; font-size: 12px; font-weight: 700;")
        version_lbl.move(106, 126)
        self.message_label = QLabel(self)
        self.message_label.setStyleSheet(
            "color: #D3D3D3; font-size: 12px; font-weight: 500; padding-left: 2px;"
        )

        # progress bar
        self.mini_progress_bar = QProgressBar()
        self.mini_progress_bar.setStyleSheet(mini_progress_bar_style)
        self.mini_progress_bar.setFixedHeight(4)
        self.mini_progress_bar.setRange(0, 0)
        self.mini_progress_bar.setObjectName("miniProgressBar")

        # message box frame
        self.message_box = QFrame()
        self.message_box.setObjectName("messageBox")
        self.message_box.setStyleSheet(message_box_frame_style)
        self.frame_layout = QVBoxLayout(self.message_box)
        self.frame_layout.setContentsMargins(0, 0, 0, 0)
        self.frame_layout.setSpacing(0)
        self.frame_layout.addWidget(
            self.message_label, alignment=Qt.AlignmentFlag.AlignLeft
        )
        self.frame_layout.addWidget(self.mini_progress_bar, stretch=1)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(2, 0, 2, 2)
        self.main_layout.addWidget(
            self.message_box, stretch=1, alignment=Qt.AlignmentFlag.AlignBottom
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.splash_img.setFixedSize(self.size())

    @Slot(str)
    def updateMessageBox(self, msg: str) -> None:
        self.message_label.setText(msg)
