from transmission_rpc import (
    from_url as TransmissionClientFromUrl,
    TransmissionError,
    TransmissionAuthError,
    TransmissionConnectError,
    TransmissionTimeoutError,
)
from pathlib import Path

from src.exceptions import TrackerClientError
from src.payloads.clients import TorrentClient


class TransmissionClient:
    """
    Transmission Client

    Note: Automatically logs in.
    """

    def __init__(self, config: TorrentClient, timeout: int = 10) -> None:
        self.config = config
        self.transmission_config = config
        self.timeout = timeout

        try:
            self.client = TransmissionClientFromUrl(
                url=self.transmission_config.host, timeout=self.timeout
            )
        except TransmissionAuthError as credential_error:
            raise TrackerClientError(
                f"Username and/or password is incorrect: {credential_error}"
            )
        except TransmissionTimeoutError as timeout_error:
            raise TrackerClientError(
                f"Timed out while trying to connect to Transmission: {timeout_error}"
            )
        except TransmissionConnectError as daemon_error:
            raise TrackerClientError(f"Transmission daemon error: {daemon_error}")
        except TransmissionError as communication_error:
            raise TrackerClientError(
                f"Failed to communicate with Transmission: {communication_error}"
            )
        except Exception as e:
            raise TrackerClientError(
                f"Unexpected Error initializing Transmission client: {e}"
            )

    def test(self) -> tuple[bool, str]:
        if self.client.session_stats():
            return (
                True,
                "Login successful! If your label/path is setup correctly (if applicable) injection should work.",
            )
        return False, "Failed"

    def inject_torrent(self, torrent_path: Path) -> tuple[bool, str]:
        try:
            add_torrent = self.client.add_torrent(
                torrent=torrent_path,
                download_dir=self._get_save_directory(),
                labels=self._get_label(),
                timeout=self.timeout,
            )
            if add_torrent and add_torrent.hash_string:
                return True, "Transmission injection successful"
            else:
                return False, "Transmission injection failed"
        except TransmissionTimeoutError as timeout_error:
            raise TrackerClientError(
                f"Timed out while trying to connect to Transmission: {timeout_error}"
            )
        except TransmissionConnectError as daemon_error:
            raise TrackerClientError(f"Transmission daemon error: {daemon_error}")
        except TransmissionError as communication_error:
            raise TrackerClientError(
                f"Failed to communicate with Transmission: {communication_error}"
            )
        except Exception as e:
            raise TrackerClientError(
                f"Unexpected Error initializing Transmission client: {e}"
            )

    def _get_label(self) -> tuple[str] | None:
        label = self.transmission_config.specific_params.get("label", "").strip()
        return (label,) if label else None

    def _get_save_directory(self) -> str | None:
        path = self.transmission_config.specific_params.get("path", "").strip()
        return path if path else None
