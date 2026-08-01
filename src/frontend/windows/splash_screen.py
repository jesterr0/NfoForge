from pathlib import Path
import traceback

from PySide6.QtCore import (
    QEvent,
    QObject,
    QSize,
    QThread,
    Signal,
    SignalInstance,
    Slot,
)
from PySide6.QtGui import (
    QCursor,
    QGuiApplication,
    QKeyEvent,
    QKeySequence,
    QPixmap,
    QShortcut,
    QShowEvent,
    Qt,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)
import qtawesome as qta

from src.backend.utils.working_dir import RUNTIME_DIR
from src.config.config import ConfigManager
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.wizards.media_input import MediaInput
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
                padding: 3px;
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
    success = Signal(str)

    def __init__(
        self,
        config: ConfigManager,
        update_splash_msg: SignalInstance,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.update_splash_msg = update_splash_msg

    def run(self) -> None:
        try:
            warning = self.init_plugins()
            self.success.emit(warning or "")
        except Exception as error:
            self.error_message.emit(
                f"Unhandled error: {error}\n{traceback.format_exc()}"
            )

    def init_plugins(self) -> str | None:
        # built in plugins
        self._update_built_in_plugins()

        # load user plugins
        plugin_loader = PluginLoader(self.update_splash_msg)
        loaded_plugins = plugin_loader.load_plugins()
        self.config.plugin_registry.plugins.update(loaded_plugins)
        self._update_flat_filters_with_plugins()

        # check if we have missing keys and remove them from the running config
        plugin_names = self.config.plugin_registry.plugins.keys()
        if self.config.settings.plugins.wizard_page not in plugin_names:
            self.config.settings.plugins.wizard_page = None
        if self.config.settings.plugins.token_replacer not in plugin_names:
            self.config.settings.plugins.token_replacer = None
        if self.config.settings.plugins.pre_upload not in plugin_names:
            self.config.settings.plugins.pre_upload = None
        if self.config.settings.plugins.metadata_provider not in plugin_names:
            self.config.settings.plugins.metadata_provider = None
        self.config.save()

        if plugin_loader.failures:
            failures = "\n".join(f"- {failure}" for failure in plugin_loader.failures)
            return (
                "The following plugins could not be loaded and were skipped:\n\n"
                f"{failures}\n\n"
                "See the application log for full error details."
            )
        return None

    def _update_built_in_plugins(self) -> None:
        built_in_plugins = {
            "Input (built in, external plugin slot disabled)": PluginPayload(
                name="Input (built in, external plugin slot disabled)",
                wizard=MediaInput,
            ),
            "Default Token Replacer (built in, external plugin slot disabled)": PluginPayload(
                name="Token Replacer (built in, external plugin slot disabled)",
                token_replacer=False,
            ),
            "Default Pre Upload (built in, external plugin slot disabled)": PluginPayload(
                name="Default Pre Upload (built in, external plugin slot disabled)",
                pre_upload=False,
            ),
            "TMDb Metadata (built in, external plugin slot disabled)": PluginPayload(
                name="TMDb Metadata (built in, external plugin slot disabled)",
                metadata_provider=False,
            ),
        }
        self.config.plugin_registry.plugins.update(built_in_plugins)

    def _update_flat_filters_with_plugins(self) -> None:
        for plugin in self.config.plugin_registry.plugins.values():
            flat_filters = getattr(plugin, "flat_filters", None)
            if flat_filters:
                self.config.plugin_registry.flat_filters.update(flat_filters)


class SplashScreen(QWidget):
    update_message_box = Signal(str)
    config_selected = Signal(str)
    # parent listens for us to call this to exit the application cleanly
    exit_app = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.resize(426, 240)
        self._set_open_screen()
        self.setCursor(Qt.CursorShape.BusyCursor)

        # config selector widgets (initially hidden)
        self.config_selector_frame: QFrame | None = None
        self.config_combo: CustomComboBox | None = None
        self.config_cont_btn: QPushButton | None = None
        self._continue_shortcuts: list[QShortcut] = []

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
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(2, 2, 2, 2)
        self.main_layout.addSpacerItem(
            QSpacerItem(
                1, 1, QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
            )
        )
        self._create_config_selector_widgets()
        self.main_layout.addWidget(
            self.message_box, alignment=Qt.AlignmentFlag.AlignBottom
        )

        # best effort to ensure window is brought to the front of all other windows
        self.raise_()
        self.activateWindow()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.splash_img.setFixedSize(self.size())

    @Slot(str)
    def updateMessageBox(self, msg: str) -> None:
        self.message_label.setText(msg)

    def show_config_selector(
        self,
        config_names: list[str] | None,
        selected_config: str | None = None,
    ) -> None:
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
            if selected_config:
                selected_index = self.config_combo.findText(
                    selected_config, Qt.MatchFlag.MatchExactly
                )
                if selected_index >= 0:
                    self.config_combo.setCurrentIndex(selected_index)

        # show the config selector
        if self.config_selector_frame:
            self.config_selector_frame.show()
        if self.config_combo:
            self.config_combo.setFocus(Qt.FocusReason.OtherFocusReason)
        for shortcut in self._continue_shortcuts:
            shortcut.setEnabled(True)
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
        self.config_combo.installEventFilter(self)
        line_edit = self.config_combo.lineEdit()
        if line_edit is not None:
            line_edit.installEventFilter(self)

        self.config_cont_btn = QPushButton(self)
        self.config_cont_btn.setIcon(qta.icon("ph.check-bold", color="#D3D3D3"))
        self.config_cont_btn.setIconSize(QSize(20, 20))
        self.config_cont_btn.setStyleSheet(config_push_button_style)
        self.config_cont_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.config_cont_btn.setToolTip("Continue with selected configuration")
        self.config_cont_btn.clicked.connect(self._on_continue_clicked)

        self._continue_shortcuts = [
            QShortcut(QKeySequence("Return"), self),
            QShortcut(QKeySequence("Enter"), self),
        ]
        for shortcut in self._continue_shortcuts:
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.setEnabled(False)
            shortcut.activated.connect(self._on_continue_clicked)

        self.cancel_btn = QPushButton(self)
        self.cancel_btn.setIcon(qta.icon("ph.x-bold", color="#D3D3D3"))
        self.cancel_btn.setIconSize(QSize(20, 20))
        self.cancel_btn.setStyleSheet(config_push_button_style)
        self.cancel_btn.setToolTip("Close application")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # exits the app when clicked
        self.cancel_btn.clicked.connect(self.exit_app.emit)

        config_layout = QHBoxLayout(self.config_selector_frame)
        config_layout.setContentsMargins(4, 4, 4, 4)
        config_layout.addWidget(self.config_combo, stretch=1)
        config_layout.addWidget(self.config_cont_btn)
        config_layout.addWidget(self.cancel_btn)

        # add to main layout (insert above message box)
        self.main_layout.insertWidget(
            0,
            self.config_selector_frame,
            stretch=1,
            alignment=Qt.AlignmentFlag.AlignBottom,
        )
        self.config_selector_frame.hide()

    @Slot()
    def _on_continue_clicked(self) -> None:
        """Handle continue button click."""
        if self.config_combo and self.config_combo.currentText():
            selected_config = self.config_combo.currentText()

            # hide config selector and show loading state
            if self.config_selector_frame:
                self.config_selector_frame.hide()
            for shortcut in self._continue_shortcuts:
                shortcut.setEnabled(False)
            self.mini_progress_bar.show()
            self.setCursor(Qt.CursorShape.BusyCursor)

            self.config_selected.emit(selected_config)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Allow Enter to continue while focus is inside the config selector."""
        combo = self.config_combo
        line_edit = combo.lineEdit() if combo is not None else None
        if (
            combo is not None
            and (watched is combo or watched is line_edit)
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and combo.currentText()
        ):
            self._on_continue_clicked()
            return True
        return super().eventFilter(watched, event)

    def _set_open_screen(self) -> None:
        """Open on active display based on mouse location and then primary screen."""
        active_screen = (
            QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        )
        self.move(active_screen.availableGeometry().center() - self.rect().center())

        self.update_message_box.connect(self.updateMessageBox)
