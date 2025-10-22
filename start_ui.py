# relevant documentation
# https://doc.qt.io/qtforpython-6/index.html#
import sys
import traceback
from multiprocessing import freeze_support as mp_freeze_support
from pathlib import Path

from PySide6.QtCore import QTimer, QtMsgType, Slot, qInstallMessageHandler
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from src.backend.utils.working_dir import IS_FROZEN, RUNTIME_DIR
from src.config.config import Config
from src.frontend.custom_widgets.scrollable_error_dialog import ScrollableErrorDialog
from src.frontend.windows.main_window import MainWindow
from src.frontend.windows.splash_screen import SplashScreen, SplashScreenLoader
from src.logger.nfo_forge_logger import LOG


class NfoForge:
    def __init__(self, arg_parse: tuple[str | None, str | None]) -> None:
        self.app = QApplication(sys.argv)

        self.app.setWindowIcon(
            QIcon(str(Path(RUNTIME_DIR / "images" / "hammer_merged.png")))
        )
        self.app.setStyle("Fusion")

        self.config_file, self.arg_parse_msg = arg_parse

        # check if there is any messages from arg parser
        if not self._arg_parse_msg():
            return

        self._setup_exception_hooks()
        self._setup_font()

        # show splash screen
        self.splash_screen = SplashScreen()
        self.splash_screen.show()
        self.splash_screen.updateMessageBox("Loading...")

        # initialize app
        QTimer.singleShot(500, self._init_app)

        self.splash_screen_loader: SplashScreenLoader | None = None
        self.config: Config | None = None
        self.main_window: MainWindow | None = None

        sys.exit(self.app.exec())

    def _arg_parse_msg(self) -> bool:
        if self.arg_parse_msg:
            msg_box = QMessageBox(
                QMessageBox.Icon.Information,
                "Args",
                self.arg_parse_msg,
                QMessageBox.StandardButton.Ok,
            )
            msg_box.exec()
            self.app.quit()
            return False
        return True

    def _setup_exception_hooks(self) -> None:
        sys.excepthook = self.exception_handler
        qInstallMessageHandler(self.qt_message_handler)

    def _setup_font(self) -> None:
        font_folder = RUNTIME_DIR / "fonts"

        for font_file in font_folder.rglob("*.ttf"):
            QFontDatabase.addApplicationFont(str(font_file))

        desired_font = "Roboto"
        font = QFont(desired_font, 9)
        check_family = font.family()
        if check_family != desired_font:
            LOG.warning(
                LOG.LOG_SOURCE.FE,
                f"Failed to load font {desired_font}, defaulting to {check_family}.",
            )

        self.app.setFont(font)

    def _init_app(self) -> None:
        # check for multiple configs and show selector if needed
        available_configs = self._get_available_configs()
        if not self.config_file and available_configs and len(available_configs) > 1:
            self.splash_screen.show_config_selector(available_configs)
            self.splash_screen.config_selected.connect(self._on_config_selected)
            return

        self._continue_init()

    def _continue_init(self) -> None:
        # setup config
        self.splash_screen.updateMessageBox("Initializing config")
        self.config = Config(self.config_file)
        if not self.config:
            raise AttributeError("Failed to load config")

        # setup loader
        self.splash_screen_loader = SplashScreenLoader(
            self.config, self.splash_screen.update_message_box, parent=self.app
        )
        self.splash_screen_loader.error_message.connect(self._error_on_splash)
        self.splash_screen_loader.success.connect(self._load_main_window)
        self.splash_screen_loader.start()

    @Slot(str)
    def _error_on_splash(self, error: str) -> None:
        if error:
            QMessageBox.critical(self.splash_screen, "Error", error)
            QApplication.quit()

    @Slot()
    def _load_main_window(self) -> None:
        self.splash_screen.update_message_box.emit("Loading main window")
        if not self.config:
            raise AttributeError("Failed to load config")

        try:
            self.main_window = MainWindow(self.config)
        except Exception as error:
            self._error_message_box(
                "Unhandled Exception", str(error), traceback.format_exc()
            )
            self.app.exit()
            return

        self.splash_screen.close()
        self.main_window.show()

    def _get_available_configs(self) -> list[str] | None:
        """Get list of available config file names (without .toml extension)"""
        try:
            config_dir = Config.USER_CONFIG_DIR
            if not config_dir.exists():
                return
            return sorted([x.stem for x in config_dir.glob("*.toml")])
        except Exception:
            pass

    @Slot(str)
    def _on_config_selected(self, selected_config: str) -> None:
        """Handle profile selection from splash screen"""
        self.config_file = selected_config
        self._continue_init()

    def exception_handler(self, exc_type, exc_value, exc_traceback) -> None:
        """Global exception handler for unhandled Python exceptions."""
        full_traceback = "".join(
            traceback.format_exception(exc_type, exc_value, exc_traceback)
        )
        error_message = f"Unhandled exception:\n{exc_value}\n\n{full_traceback}"
        LOG.critical(LOG.LOG_SOURCE.FE, error_message)
        self._error_message_box("Unhandled Exception", error_message)
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    def qt_message_handler(self, mode, _context, message) -> None:
        """Handler for Qt-specific warnings and errors."""
        if mode in (
            QtMsgType.QtWarningMsg,
            QtMsgType.QtCriticalMsg,
            QtMsgType.QtFatalMsg,
        ):
            LOG.critical(LOG.LOG_SOURCE.FE, f"Qt Error: {message}")
            self._error_message_box("QtError", message)

    def _error_message_box(
        self, title: str, message: str, traceback: str | None = None
    ) -> None:
        detect_parent = (
            self.splash_screen
            if self.splash_screen and self.splash_screen.isVisible()
            else self.main_window
        )
        if detect_parent:
            if traceback:
                traceback = f"\n{traceback}"
            err_msg_box = ScrollableErrorDialog(
                f"{message}{traceback if traceback else ''}",
                title=title,
                parent=detect_parent,
            )
            err_msg_box.exec()
            if self.splash_screen.isVisible():
                self.app.quit()


def arg_parse() -> tuple[str | None, str | None]:
    config_arg = None
    message_arg = None
    args = sys.argv
    length = len(args)
    if length == 2 and args[1] in ("--help", "-h", "help", "h"):
        message_arg = (
            "-c/--config <config_file> (Loads the program with desired config)"
            "\n-h/--help (Displays this message)"
        )
    elif length == 3 and args[1] in ("--config", "-c", "config", "c"):
        config_arg = args[2]
        if config_arg.lower().endswith(".toml"):
            config_arg = config_arg[:-5]
    return config_arg, message_arg


if __name__ == "__main__":
    if IS_FROZEN:
        # required for multiprocessing support when the app is frozen (exe)
        mp_freeze_support()
    NfoForge(arg_parse())
