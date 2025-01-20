import webbrowser
from PySide6.QtWidgets import (
    QMainWindow,
    QStackedWidget,
    QMessageBox,
    QStatusBar,
    QLabel,
)
from PySide6.QtCore import QByteArray, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut

from src.config.config import Config
from src.enums.screen_shot_mode import ScreenShotMode
from src.enums.settings_window import SettingsTabs
from src.frontend.utils.main_window_utils import MainWindowWorker
from src.frontend.wizards.wizard import MainWindowWizard
from src.frontend.stacked_windows.settings.settings import Settings
from src.logger.nfo_forge_logger import LOG
from src.backend.main_window import kill_child_processes
from src.version import program_name, __version__


class MainWindow(QMainWindow):
    settings_clicked = Signal()
    set_disabled = Signal(bool)
    wizard_set_disabled = Signal(bool)
    wizard_end_early = Signal()
    wizard_next_button_change_txt = Signal(str)
    wizard_next_button_reset_txt = Signal()
    wizard_process_btn_clicked = Signal()
    wizard_process_btn_change_txt = Signal(str)
    wizard_process_btn_set_hidden = Signal()
    hide_main_window = Signal(bool)
    update_status_bar = Signal(str, int)  # message, timeout[milliseconds]
    clear_status_bar = Signal()
    update_status_bar_label = Signal(str)
    open_log_dir = Signal()

    def __init__(self, config: Config):
        super().__init__()

        # setup window
        self.setObjectName("MainWindow")
        self.default_window_title = f"{program_name} {__version__}"
        self.setWindowTitle(self.default_window_title)
        self.status_bar = QStatusBar()
        self.update_status_bar.connect(self.update_status_tip)
        self.clear_status_bar.connect(self.clear_message)
        self.update_status_bar_label.connect(self.update_status_label)
        self.setStatusBar(self.status_bar)
        self.resize(650, 550)
        self.config = config
        self.restore_window_settings()
        self.status_profile_label = QLabel(
            f"Profile: {str(self.config.cfg_payload.profile).title()}", self
        )
        self.status_bar.addPermanentWidget(self.status_profile_label)
        self._check_suffix()

        # check dependencies
        QTimer.singleShot(1, self._check_dependencies)

        # init logger
        QTimer.singleShot(2, self.setup_logger)

        # connect signals
        self.settings_clicked.connect(self._open_settings_window)
        self.set_disabled.connect(self._toggle_state)
        self.hide_main_window.connect(self.hide_window)
        self.open_log_dir.connect(self.open_logs)

        # wizard (main stacked widget)
        self.wizard = MainWindowWizard(self.config, self)
        self.wizard_set_disabled.connect(lambda e: self.wizard.set_disabled.emit(e))
        self.wizard_end_early.connect(self.wizard.end_early)

        # additional stacked widgets (windows)
        self.settings = Settings(self.config, self)
        self.settings.close_settings.connect(self._close_settings)

        self.stacked_widget = QStackedWidget(self)
        self.stacked_widget.addWidget(self.wizard)
        self.stacked_widget.addWidget(self.settings)

        self.setCentralWidget(self.stacked_widget)

        # key binds
        self.open_log_dir_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        self.open_log_dir_shortcut.activated.connect(self.open_logs)

    @Slot()
    def _close_settings(self) -> None:
        self.wizard.reset_wizard()
        self.stacked_widget.setCurrentWidget(self.wizard)
        self._check_suffix()

    @Slot()
    def _open_settings_window(self) -> None:
        self.stacked_widget.setCurrentWidget(self.settings)

    @Slot(bool)
    def _toggle_state(self, state: bool) -> None:
        self.setDisabled(state)

    def _check_suffix(self) -> None:
        title = self.default_window_title
        if self.config.cfg_payload.ui_suffix:
            if len(self.config.cfg_payload.ui_suffix) > 30:
                self.config.cfg_payload.ui_suffix = (
                    f"{self.config.cfg_payload.ui_suffix[0:31]}..."
                )
            title = f"{title} - {self.config.cfg_payload.ui_suffix}"
        self.setWindowTitle(title)

    def _check_dependencies(self) -> None:
        if self.config.cfg_payload.screenshots_enabled:
            ss_mode = self.config.cfg_payload.ss_mode
            if ss_mode in (
                ScreenShotMode.BASIC_SS_GEN,
                ScreenShotMode.SIMPLE_SS_COMP,
            ):
                ffmpeg = self.config.cfg_payload.ffmpeg
                if not ffmpeg or (ffmpeg and not ffmpeg.exists()):
                    QMessageBox.critical(
                        self,
                        "Dependency Error",
                        (
                            "FFMPEG isn't detected and is required for basic and "
                            "simple comparison screenshots.\n\nDisabling image "
                            "generation until executable path is provided."
                        ),
                    )
                    self.config.cfg_payload.screenshots_enabled = False
                    self.config.save_config()
                    self.settings.re_load_settings.emit()
                    self.stacked_widget.setCurrentWidget(self.settings)
                    self.settings.swap_tab.emit(SettingsTabs.DEPENDENCIES_SETTINGS)

            elif ss_mode == ScreenShotMode.ADV_SS_COMP:
                frame_forge = self.config.cfg_payload.frame_forge
                if not frame_forge or (frame_forge and not frame_forge.exists()):
                    QMessageBox.critical(
                        self,
                        "Dependency Error",
                        (
                            "FrameForge isn't detected and is required for advanced "
                            "comparison screenshots.\n\nDisabling image "
                            "generation until executable path is provided."
                        ),
                    )
                    self.config.cfg_payload.screenshots_enabled = False
                    self.config.save_config()
                    self.settings.re_load_settings.emit()
                    self.stacked_widget.setCurrentWidget(self.settings)
                    self.settings.swap_tab.emit(SettingsTabs.DEPENDENCIES_SETTINGS)

    def setup_logger(self) -> None:
        threaded_worker = MainWindowWorker(self._setup_logger, parent=self)
        threaded_worker.start()

    def _setup_logger(self) -> None:
        """Ran by threaded worker"""
        LOG.set_log_level(self.config.cfg_payload.log_level)
        LOG.clean_up_logs(self.config.cfg_payload.log_total)

    @Slot(str, int)
    def update_status_tip(self, message: str, timer: int) -> None:
        message = message if message else ""
        if timer > 0:
            self.status_bar.showMessage(message, timer)
        else:
            self.status_bar.showMessage(message)

    @Slot()
    def clear_status_tip(self) -> None:
        self.status_bar.clearMessage()

    @Slot(str)
    def update_status_label(self, data: str) -> None:
        self.status_profile_label.setText(data)

    @Slot()
    def clear_message(self) -> None:
        self.status_bar.showMessage("")

    @Slot()
    def open_logs(self) -> None:
        if LOG.log_file.exists():
            webbrowser.open(str(LOG.log_file))
        elif LOG.log_file.parent.exists():
            webbrowser.open(str(LOG.log_file.parent))

    @Slot(object)
    def closeEvent(self, event: QCloseEvent) -> None:
        kill_child_processes()
        self.save_window_settings()
        super().closeEvent(event)

    def save_window_settings(self) -> None:
        geometry = str(self.saveGeometry().toBase64().data(), encoding="utf-8")
        self.config.program_conf.main_window_position = geometry
        self.config.save_program_conf()

    def restore_window_settings(self) -> None:
        geometry = self.config.program_conf.main_window_position
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode("utf-8")))

    @Slot(bool)
    def hide_window(self, hide: bool) -> None:
        if hide:
            self.hide()
        else:
            self.show()
