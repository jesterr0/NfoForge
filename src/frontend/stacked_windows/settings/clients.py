from PySide6.QtCore import Slot

from src.enums.torrent_client import TorrentClientSelection
from src.frontend.custom_widgets.client_listbox import ClientListWidget
from src.frontend.global_signals import GSigs
from src.frontend.stacked_windows.settings.base import BaseSettings


class ClientsSettings(BaseSettings):
    def __init__(self, config, main_window, parent) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("clientsSettings")

        self.client_widget = ClientListWidget(self.config, self)
        self.client_widget.testing_started.connect(self._testing_started)
        self.client_widget.testing_ended.connect(self._testing_ended)
        self.add_widget(self.client_widget, add_stretch=True, stretch=1)

        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)

        self._load_saved_settings()

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
        """Applies user saved settings from the config"""
        self.client_widget.add_items(self.config.client_map)

    @Slot()
    def _save_settings(self) -> None:
        for client in TorrentClientSelection:
            self.client_widget.save_client_info(client)
        self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self._load_saved_settings()
