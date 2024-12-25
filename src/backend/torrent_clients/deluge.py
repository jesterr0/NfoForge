from deluge_web_client.client import DelugeWebClient
from pathlib import Path

from src.config.config import Config
from src.exceptions import TrackerClientError


class DelugeClient:
    """Deluge Web Client"""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.deluge_config = config.cfg_payload.deluge

        self.client = DelugeWebClient(
            url=self.deluge_config.host, password=self.deluge_config.password
        )

    def login(self) -> tuple[bool, str]:
        try:
            login = self.client.login()
            if not login.result or login.error:
                raise TrackerClientError("Failed to login")
            return True, "Login successful"
        except Exception as e:
            raise TrackerClientError(f"Failed to login: {e}")

    def logout(self) -> None:
        try:
            self.client.close_session()
        except Exception as e:
            raise TrackerClientError(f"Failed to logout: {e}")

    def inject_torrent(self, torrent_path: Path) -> tuple[bool, str]:
        try:
            inject = self.client.upload_torrent(
                torrent_path=torrent_path,
                seed_mode=True,
                auto_managed=True,
                save_directory=self._get_save_directory(),
                label=self._get_label(),
            )
            if not inject.error and inject.result:
                return True, "Deluge injection successful"
            return False, "Deluge injection failed"
        except Exception as e:
            raise TrackerClientError(f"Failed to inject torrent: {e}")

    def _get_label(self) -> str | None:
        label = self.deluge_config.specific_params.get("label", "").strip()
        return label if label else None

    def _get_save_directory(self) -> str | None:
        path = self.deluge_config.specific_params.get("path", "").strip()
        return path if path else None
