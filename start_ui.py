import traceback
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtCore import QTimer, QtMsgType, qInstallMessageHandler, Slot

from src.config.config import Config
from src.logger.nfo_forge_logger import LOG
from src.frontend.windows.splash_screen import SplashScreen, SplashScreenLoader
from src.frontend.windows.main_window import MainWindow
from src.backend.utils.working_dir import RUNTIME_DIR


class NfoForge:
    def __init__(self) -> None:
        self.app = QApplication(sys.argv)
        self.app.setWindowIcon(
            QIcon(str(Path(RUNTIME_DIR / "images" / "hammer_merged.png")))
        )
        self.app.setStyle("Fusion")

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
        # setup config
        self.splash_screen.updateMessageBox("Initializing config")
        self.config = Config()
        if not self.config:
            raise AttributeError("Failed to load config")

        # setup loader
        self.splash_screen_loader = SplashScreenLoader(
            self.config, self.splash_screen.update_message_box
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
            QMessageBox.critical(detect_parent, title, f"{message}{traceback}")
            if self.splash_screen.isVisible():
                self.app.quit()


if __name__ == "__main__":
    NfoForge()


# TODO's
# TODO: Setup a configuration that can increase the scale of the entire program by a %.
# TODO: Remember last used path globally for all file dialogues
# TODO: Check to ensure long path is enabled on Windows

# main window
# TODO: need to add a string limit for ui suffix
