from PySide6.QtCore import Slot

from src.enums.torrent_client import TorrentClientSelection
from src.frontend.stacked_windows.settings.base import BaseSettings
from src.frontend.custom_widgets.client_listbox import ClientListWidget


class ClientsSettings(BaseSettings):
    def __init__(self, config, main_window, parent) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("clientsSettings")

        self.client_widget = ClientListWidget(self.config, False, self)
        self.inner_layout.removeItem(self._spacer_item)
        self.inner_layout.addWidget(self.client_widget, stretch=1)

        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)

        self._load_saved_settings()

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
