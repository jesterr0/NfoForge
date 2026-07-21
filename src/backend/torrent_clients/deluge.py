from pathlib import Path

from deluge_web_client import DelugeWebClient, TorrentOptions

from src.exceptions import TrackerClientError
from src.payloads.clients import TorrentClient


class DelugeClient:
    """Deluge Web Client"""

    def __init__(self, config: TorrentClient, timeout: int = 10) -> None:
        self.deluge_config = config
        self.timeout = timeout

        if not self.deluge_config.host or not self.deluge_config.password:
            raise TrackerClientError(
                "Host and password must be defined when initializing DelugeClient"
            )

        self.client = DelugeWebClient(
            url=self.deluge_config.host, password=self.deluge_config.password
        )

    def login(self) -> tuple[bool, str]:
        try:
            login = self.client.login(timeout=self.timeout)
            if not login.result or login.error:
                reason = login.error or login.message or "Unknown login failure"
                raise TrackerClientError(f"Failed to login: {reason}")
            return True, "Login successful"
        except TrackerClientError:
            raise
        except Exception as error:
            raise TrackerClientError(f"Failed to login: {error}") from error

    def logout(self) -> None:
        try:
            self.client.close_session()
        except Exception as error:
            raise TrackerClientError(f"Failed to logout: {error}") from error

    def test(self) -> tuple[bool, str]:
        try:
            self.login()
            return (
                True,
                "Login successful! If your label/path is configured correctly, injection should work.",
            )
        except TrackerClientError as error:
            return False, str(error)

    def inject_torrent(self, torrent_path: Path) -> tuple[bool, str]:
        try:
            inject = self.client.upload_torrent(
                torrent_path=torrent_path,
                torrent_options=TorrentOptions(
                    seed_mode=True,
                    auto_managed=True,
                    download_location=self._get_save_directory(),
                    label=self._get_label(),
                ),
                timeout=self.timeout,
            )
            if not inject.error and inject.result:
                return True, inject.message or "Deluge injection successful"
            reason = inject.error or inject.message or "Unknown upload failure"
            return False, f"Deluge injection failed: {reason}"
        except Exception as error:
            raise TrackerClientError(f"Failed to inject torrent: {error}") from error

    def _get_label(self) -> str | None:
        label = self.deluge_config.specific_params.get("label")
        return label.strip() or None if isinstance(label, str) else None

    def _get_save_directory(self) -> str | None:
        path = self.deluge_config.specific_params.get("path")
        return path.strip() or None if isinstance(path, str) else None
