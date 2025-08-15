from pathlib import Path
import traceback
from typing import Type

from PySide6.QtCore import QThread, Signal, SignalInstance, Slot
from PySide6.QtGui import QPixmap, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.backend.utils.working_dir import RUNTIME_DIR
from src.config.config import Config
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.wizards.media_input_advanced import MediaInputAdvanced
from src.frontend.wizards.media_input_basic import MediaInputBasic
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.plugins.loader import PluginLoader
from src.plugins.plugin_payload import PluginPayload
from src.version import __version__

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


config_splash_combo_style = """
            QComboBox {{
                color: #D3D3D3;
                background-color: rgba(45, 49, 54, 0.9);
                border: 1px solid #777;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: 11px;
            }}
            QComboBox:hover {{
                border-color: #fb641a;
            }}
            QComboBox::drop-down {{
                border: none;
                background-color: rgba(75, 80, 85, 0.9);
                width: 20px;
                border-top-right-radius: 3px;
                border-bottom-right-radius: 3px;
            }}
            QComboBox::drop-down:hover {{
                background-color: rgba(85, 90, 95, 0.9);
            }}
            QComboBox::down-arrow {{
                image: url({});
                width: 18;
                height: 18;
            }}
            QComboBox QAbstractItemView {{
                color: #D3D3D3;
                background-color: rgba(45, 49, 54, 0.95);
                border: 1px solid #555;
                border-radius: 3px;
                selection-background-color: #fb641a;
                selection-color: white;
                font-size: 11px;
            }}
            QComboBox QAbstractItemView::item {{
                color: #D3D3D3;
                background-color: rgba(45, 49, 54, 0.95);
                padding: 4px 8px;
                border: none;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: rgba(251, 100, 26, 0.3);
                color: white;
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: #fb641a;
                color: white;
            }}
        """

config_push_button_style = """
            QPushButton {
                color: #D3D3D3;
                background-color: #fb641a;
                border: none;
                border-radius: 3px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #e55a17;
            }
            QPushButton:pressed {
                background-color: #d4510f;
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
        self._update_jinja2_engine_with_plugins()

        # check if we have missing keys and remove them from the running config
        plugins = self.config.loaded_plugins.keys()
        if self.config.cfg_payload.wizard_page not in plugins:
            self.config.cfg_payload.wizard_page = None
        if self.config.cfg_payload.token_replacer not in plugins:
            self.config.cfg_payload.token_replacer = None
        self.config.save_config()

    def _update_built_in_plugins(self) -> None:
        built_in_plugins = {
            "Basic (built in, external plugin slot disabled)": PluginPayload(
                name="Basic (built in, external plugin slot disabled)",
                wizard=MediaInputBasic,
            ),
            "Advanced (built in, external plugin slot disabled)": PluginPayload(
                name="Advanced (built in, external plugin slot disabled)",
                wizard=MediaInputAdvanced,
            ),
            "Default Token Replacer (built in, external plugin slot disabled)": PluginPayload(
                name="Token Replacer (built in, external plugin slot disabled)",
                token_replacer=False,
            ),
            "Default Pre Upload (built in, external plugin slot disabled)": PluginPayload(
                name="Default Pre Upload (built in, external plugin slot disabled)",
                pre_upload=False,
            ),
        }
        self.config.loaded_plugins.update(built_in_plugins)

    def _update_jinja2_engine_with_plugins(self) -> None:
        for plugin in self.config.loaded_plugins.values():
            jinja2_filters = getattr(plugin, "jinja2_filters", None)
            jinja2_functions = getattr(plugin, "jinja2_functions", None)
            if jinja2_filters:
                for name, func in jinja2_filters.items():
                    self.config.jinja_engine.add_filter(name, func)

            if jinja2_functions:
                for name, func in jinja2_functions.items():
                    self.config.jinja_engine.add_global(name, func, False)


class SplashScreen(QWidget):
    update_message_box = Signal(str)
    config_selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.resize(426, 240)
        self.setCursor(Qt.CursorShape.BusyCursor)

        self.update_message_box.connect(self.updateMessageBox)

        # config selector widgets (initially hidden)
        self.config_selector_frame: QFrame | None = None
        self.config_combo: CustomComboBox | None = None
        self.config_cont_btn: QPushButton | None = None

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
        self.frame_layout.setContentsMargins(0, 2, 0, 2)
        self.frame_layout.setSpacing(0)
        self.frame_layout.addWidget(
            self.message_label, alignment=Qt.AlignmentFlag.AlignLeft
        )
        self.frame_layout.addWidget(self.mini_progress_bar, stretch=1)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(2, 2, 2, 2)
        self.main_layout.addWidget(
            self.message_box, stretch=1, alignment=Qt.AlignmentFlag.AlignBottom
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.splash_img.setFixedSize(self.size())

    @Slot(str)
    def updateMessageBox(self, msg: str) -> None:
        self.message_label.setText(msg)

    def show_config_selector(self, config_names: list[str] | None) -> None:
        """Show config selector dropdown with available configs"""
        if not config_names:
            return

        # hide progress bar and change message
        self.mini_progress_bar.hide()
        self.message_label.setText("Select Config")

        # create config selector widgets if they don't exist
        if not self.config_selector_frame:
            self._create_config_selector_widgets()

        # populate combo box with config names
        if self.config_combo:
            self.config_combo.clear()
            self.config_combo.addItems(config_names)

        # show the config selector
        if self.config_selector_frame:
            self.config_selector_frame.show()
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _create_config_selector_widgets(self) -> None:
        """Create the config selector UI widgets"""

        # create frame for config selector
        self.config_selector_frame = QFrame()
        self.config_selector_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(28, 31, 34, 0.9);
                padding: 4px;
            }
        """)

        # create combo box for config selection
        self.config_combo = CustomComboBox(
            completer=True,
            completer_strict=True,
            max_items=5,
            disable_mouse_wheel=True,
            parent=self,
        )
        self.config_combo.setStyleSheet(
            config_splash_combo_style.format(
                str(Path(RUNTIME_DIR / "svg" / "arrow_down.svg").as_posix())
            )
        )
        self.config_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.config_combo.view().setCursor(Qt.CursorShape.PointingHandCursor)

        self.config_cont_btn = QPushButton("Continue", self)
        self.config_cont_btn.setStyleSheet(config_push_button_style)
        self.config_cont_btn.clicked.connect(self._on_continue_clicked)

        config_lbl = QLabel(
            '<span style="color: #D3D3D3; font-size: medium;">Config:</span>', self
        )

        config_layout = QHBoxLayout(self.config_selector_frame)
        config_layout.setContentsMargins(4, 4, 4, 4)
        config_layout.addWidget(config_lbl)
        config_layout.addWidget(self.config_combo, stretch=1)
        config_layout.addWidget(self.config_cont_btn)

        # add to main layout (insert above message box)
        self.main_layout.insertWidget(0, self.config_selector_frame)
        self.config_selector_frame.hide()

    @Slot()
    def _on_continue_clicked(self) -> None:
        """Handle continue button click"""
        if self.config_combo and self.config_combo.currentText():
            selected_config = self.config_combo.currentText()

            # hide config selector and show loading state
            if self.config_selector_frame:
                self.config_selector_frame.hide()
            self.mini_progress_bar.show()
            self.setCursor(Qt.CursorShape.BusyCursor)

            self.config_selected.emit(selected_config)
