import copy
from dataclasses import fields
from typing import TYPE_CHECKING

from PySide6.QtCore import Slot

from src.config.config import ConfigManager
from src.config.models import TorrentClientSettings
from src.frontend.custom_widgets.client_settings import ClientSettingsWidget
from src.frontend.global_signals import GSigs
from src.frontend.stacked_windows.settings.base import BaseSettings

if TYPE_CHECKING:
    from src.frontend.stacked_windows.settings.settings import Settings
    from src.frontend.windows.main_window import MainWindow


class ClientsSettings(BaseSettings):
    """Transactional settings wrapper around the shared client editor."""

    def __init__(
        self, config: ConfigManager, main_window: "MainWindow", parent: "Settings"
    ) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("clientsSettings")

        self._working_config = self._copy_config_with_clients(
            self.config.settings.torrent_clients
        )
        self._defaults_config = self._copy_config_with_clients(
            self.config.defaults.torrent_clients
        )
        self._baseline_clients = copy.deepcopy(self.config.settings.torrent_clients)

        self.client_widget = ClientSettingsWidget(self._working_config, self)
        self.client_widget.testing_started.connect(self._testing_started)
        self.client_widget.testing_ended.connect(self._testing_ended)
        self.add_widget(self.client_widget, add_stretch=True, stretch=1)

        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)

        self._load_saved_settings()

    def _copy_config_with_clients(
        self,
        client_settings: TorrentClientSettings,
    ) -> ConfigManager:
        copied_config = copy.copy(self.config)
        copied_config.settings = copy.copy(self.config.settings)
        copied_config.settings.torrent_clients = copy.deepcopy(client_settings)
        return copied_config

    @Slot()
    def _testing_started(self) -> None:
        GSigs().main_window_set_disabled.emit(True)
        GSigs().main_window_update_status_tip.emit("Testing client please wait...", 0)

    @Slot()
    def _testing_ended(self) -> None:
        GSigs().main_window_set_disabled.emit(False)
        GSigs().main_window_clear_status_tip.emit()

    @Slot()
    def _load_saved_settings(self) -> None:
        self._working_config.settings.torrent_clients = copy.deepcopy(
            self.config.settings.torrent_clients
        )
        self._baseline_clients = copy.deepcopy(self.config.settings.torrent_clients)
        self.client_widget.load_from_config(self._working_config)

    def _apply_working_client_changes(self) -> None:
        live_clients = self.config.settings.torrent_clients.by_selection()
        working_clients = self._working_config.settings.torrent_clients.by_selection()
        baseline_clients = self._baseline_clients.by_selection()

        for client, working_info in working_clients.items():
            live_info = live_clients[client]
            baseline_info = baseline_clients[client]
            for field in fields(working_info):
                value = getattr(working_info, field.name)
                if value != getattr(baseline_info, field.name):
                    setattr(live_info, field.name, copy.deepcopy(value))

    @Slot()
    def _save_settings(self) -> None:
        self.client_widget.save_editor_settings()
        self._apply_working_client_changes()
        self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self._working_config.settings.torrent_clients = copy.deepcopy(
            self.config.settings.torrent_clients
        )
        self.client_widget.load_from_config(self._defaults_config)
