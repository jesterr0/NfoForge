from collections.abc import Sequence
from queue import Queue
from typing import Type
import webbrowser

from PySide6.QtCore import QByteArray, QTimer, Slot
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
)

from src.backend.main_window import kill_child_processes
from src.backend.utils.file_utilities import file_bytes_to_str, get_dir_size
from src.config.config import Config
from src.enums.screen_shot_mode import ScreenShotMode
from src.enums.settings_window import SettingsTabs
from src.frontend.custom_widgets.multi_prompt_dialog import MultiPromptDialog
from src.frontend.global_signals import GSigs
from src.frontend.stacked_windows.settings.settings import Settings
from src.frontend.utils.main_window_utils import MainWindowWorker
from src.frontend.utils.scaling_manager import FontScalingManager
from src.frontend.wizards.wizard import MainWindowWizard
from src.logger.nfo_forge_logger import LOG
from src.version import __version__, program_name


class MainWindow(QMainWindow):
    def __init__(self, config: Config):
        super().__init__()

        # setup window
        self.setObjectName("MainWindow")
        self.default_window_title = f"{program_name} {__version__}"
        self.setWindowTitle(self.default_window_title)
        self.status_bar = QStatusBar()
        GSigs().main_window_update_status_tip.connect(self.update_status_tip)
        GSigs().main_window_clear_status_tip.connect(self.clear_status_tip)
        GSigs().main_window_update_status_bar_label.connect(self.update_status_label)
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
        GSigs().settings_clicked.connect(self._open_settings_window)
        GSigs().main_window_set_disabled.connect(self._toggle_state)
        GSigs().main_window_hide.connect(self.hide_window)
        GSigs().main_window_open_log_dir.connect(self.open_log_directory)
        GSigs().main_window_open_log_file.connect(self.open_log)

        # thread safe prompts
        GSigs().ask_prompt.connect(self.ask_prompt)
        GSigs().ask_multi_prompt.connect(self.ask_multi_prompt)
        GSigs().ask_custom_prompt.connect(self.ask_custom_prompt)

        # timer for debounced config saving for scaling changes
        self._config_save_timer = QTimer(self, singleShot=True)
        self._config_save_timer.timeout.connect(self._save_config_debounced)

        # wizard (main stacked widget)
        self.wizard = MainWindowWizard(self.config, self)

        # additional stacked widgets (windows)
        self.settings = Settings(self.config, self)
        GSigs().settings_close.connect(self._close_settings)

        self.stacked_widget = QStackedWidget(self)
        self.stacked_widget.addWidget(self.wizard)
        self.stacked_widget.addWidget(self.settings)

        self.setCentralWidget(self.stacked_widget)

        # setup scaling manager for Electron-like zoom functionality
        self.scaling_manager = FontScalingManager(
            initial_scale_factor=config.cfg_payload.ui_scale_factor, parent=self
        )
        # setup shortcuts
        self.scaling_manager.setup_shortcuts(self)
        # connect to scaling manager signals
        self.scaling_manager.scaling_changed_by_user.connect(self._on_scaling_changed)
        # connect to settings scale factor changes (no auto-save)
        GSigs().scale_factor_set_from_settings.connect(
            self._on_scaling_changed_from_settings
        )

        # key binds
        self.open_log_dir_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        self.open_log_dir_shortcut.activated.connect(self.open_log)

        # run delayed start up tasks
        self._delayed_start_up_tasks()

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

    @Slot(float)
    def _on_scaling_changed(self, scale_factor: float) -> None:
        """Save the new scaling factor to config when it changes."""
        self.config.cfg_payload.ui_scale_factor = scale_factor

        # emit global signal to sync UI elements in general settings
        GSigs().scale_factor_changed.emit(scale_factor)

        # use debounced saving to prevent multiple rapid config writes
        self._config_save_timer.stop()
        self._config_save_timer.start(1200)

    @Slot(float)
    def _on_scaling_changed_from_settings(self, scale_factor: float) -> None:
        """Handle scaling changes from settings UI (no auto-save)."""
        self.scaling_manager.set_scale_factor(scale_factor, user_initiated=False)

    @Slot()
    def _save_config_debounced(self) -> None:
        """Debounced config save method to prevent excessive config writes."""
        try:
            self.config.save_config()
            # show brief status message to indicate save
            GSigs().main_window_update_status_tip.emit("Config saved", 1500)
        except Exception as e:
            LOG.error(LOG.LOG_SOURCE.FE, f"Failed to save config: {e}")
            GSigs().main_window_update_status_tip.emit("Failed to save config", 3000)

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
                    GSigs().settings_swap_tab.emit(SettingsTabs.DEPENDENCIES_SETTINGS)

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
                    GSigs().settings_swap_tab.emit(SettingsTabs.DEPENDENCIES_SETTINGS)

    def setup_logger(self) -> None:
        threaded_worker = MainWindowWorker(self._setup_logger, parent=self)
        threaded_worker.start()

    def _setup_logger(self) -> None:
        """Ran by threaded worker"""
        LOG.set_log_level(self.config.cfg_payload.log_level)
        LOG.clean_up_logs(self.config.cfg_payload.log_total)

    def _delayed_start_up_tasks(self) -> None:
        """Any task ran inside of this method should be triggered via a QTimer.singleShot"""
        QTimer.singleShot(3500, self.display_temp_directory_size)

    def display_temp_directory_size(self) -> None:
        size = get_dir_size(self.config.cfg_payload.working_dir)
        if size <= 0:
            return
        GSigs().main_window_update_status_tip.emit(
            f"Working directory size: {file_bytes_to_str(size)}", 8000
        )

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
    def open_log(self) -> None:
        if LOG.log_file.exists():
            webbrowser.open(str(LOG.log_file))
        elif LOG.log_file.parent.exists():
            webbrowser.open(str(LOG.log_file.parent))

    @Slot()
    def open_log_directory(self) -> None:
        if LOG.log_file.parent.exists():
            webbrowser.open(str(LOG.log_file.parent))

    @Slot(object)
    def closeEvent(self, event: QCloseEvent) -> None:
        # ensure any pending config save is completed before closing
        if self._config_save_timer.isActive():
            self._config_save_timer.stop()
            self._save_config_debounced()

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

    @Slot(str, str, object)
    def ask_prompt(self, prompt_title: str, prompt: str, queue: Queue) -> None:
        """Can be used anywhere in the program, thread safe way to get more data and return it via queue.put()"""
        user_input, ok = QInputDialog.getText(self, prompt_title, prompt)
        queue.put((ok, user_input))

    @Slot(str, object, object)
    def ask_multi_prompt(
        self, prompt_title: str, prompts: Sequence[str], queue: Queue
    ) -> None:
        result = MultiPromptDialog(prompt_title, prompts, self).get_results()
        queue.put(result)

    @Slot(object, object)
    def ask_custom_prompt(self, widget: Type[QDialog], queue: Queue) -> None:
        usr_widget = widget(self)
        usr_widget.exec()
        results = getattr(usr_widget, "results", None)
        queue.put(results)
