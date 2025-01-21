from qbittorrentapi import Client as QBitClient
import qbittorrentapi.exceptions
from pathlib import Path

from src.exceptions import TrackerClientError
from src.payloads.clients import TorrentClient


class QBittorrentClient:
    """QBittorrent Client"""

    def __init__(self, config: TorrentClient, timeout: int = 10) -> None:
        self.timeout = timeout
        self.qbit_config = config

        self.client = QBitClient(
            host=str(self.qbit_config.host),
            port=self._get_port(),
            username=str(self.qbit_config.user),
            password=str(self.qbit_config.password),
        )

    def login(self) -> tuple[bool, str]:
        try:
            self.client.auth_log_in(requests_args={"timeout": self.timeout})
            return True, "Login successful"
        except qbittorrentapi.LoginFailed as e:
            return False, f"Login failed. Check username and password: {e}"
        except qbittorrentapi.exceptions.APIConnectionError:
            return False, (
                "qBittorrent is not detected. Ensure that it's running and check host and port."
            )
        except Exception as e:
            raise TrackerClientError(f"Unexpected error during login: {e}") from e

    def logout(self) -> None:
        try:
            self.client.auth_log_out()
        except Exception as e:
            raise TrackerClientError(f"Failed to logout: {e}") from e

    def test(self) -> tuple[bool, str]:
        if self.login()[0]:
            return (
                True,
                "Login successful! If your category is setup correctly injection should work.",
            )
        return False, "Failed"

    def inject_torrent(self, torrent_file: Path) -> tuple[bool, str]:
        try:
            add_torrent = self.client.torrents_add(
                torrent_files=str(torrent_file),
                save_path=None,
                use_auto_torrent_management=True,
                is_skip_checking=True,
                category=self._get_category(),
            )
            if add_torrent == "Ok.":
                return True, "qBittorrent injection successful"
            else:
                return False, "qBittorrent injection failed"
        except qbittorrentapi.exceptions.APIError as e:
            raise TrackerClientError(f"Failed to inject torrent: {e}") from e
        except Exception as e:
            raise TrackerClientError(
                f"Unexpected error during torrent injection: {e}"
            ) from e

    def _get_category(self) -> str:
        category = self.qbit_config.specific_params.get("category")
        if not category:
            raise TrackerClientError(
                "You must supply your category in the configuration"
            )
        return category

    def _get_port(self) -> int | None:
        port = int(self.qbit_config.port)
        return port if port > 0 else None
