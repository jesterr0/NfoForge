from PySide6.QtCore import Slot
from PySide6.QtWidgets import QLabel

from src.frontend.custom_widgets.masked_qline_edit import MaskedQLineEdit
from src.frontend.stacked_windows.settings.base import BaseSettings
from src.frontend.utils import create_form_layout


class SecuritySettings(BaseSettings):
    def __init__(self, config, main_window, parent) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("securitySettings")

        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)

        tmdb_api_key_lbl = QLabel("TMDB Api Key", self)
        tmdb_api_key_lbl.setToolTip(
            "TMDB Api Key, required to determine file input metadata"
        )
        self.tmdb_api_key_entry = MaskedQLineEdit(self, masked=True)

        self.add_layout(create_form_layout(tmdb_api_key_lbl, self.tmdb_api_key_entry))
        self.add_layout(self.reset_layout, add_stretch=True)

        self._load_saved_settings()

    @Slot()
    def _load_saved_settings(self) -> None:
        """Applies user saved settings from the config"""
        payload = self.config.cfg_payload
        self.tmdb_api_key_entry.setText(payload.tmdb_api_key)

    @Slot()
    def _save_settings(self) -> None:
        self.config.cfg_payload.tmdb_api_key = self.tmdb_api_key_entry.text().strip()
        self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self.tmdb_api_key_entry.clear()
