from transmission_rpc import (
    from_url as TransmissionClientFromUrl,
    TransmissionError,
    TransmissionAuthError,
    TransmissionConnectError,
    TransmissionTimeoutError,
)
from pathlib import Path

from src.config.config import Config
from src.exceptions import TrackerClientError


class Transmission:
    """
    Transmission Client

    Note: Automatically logs in.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.transmission_config = config.cfg_payload.transmission

        try:
            self.client = TransmissionClientFromUrl(self.transmission_config.host)
        except TransmissionError as communication_error:
            raise TrackerClientError(
                f"Failed to communicate with Transmission: {communication_error}"
            )
        except TransmissionAuthError as credential_error:
            raise TrackerClientError(
                f"Username and/or password is incorrect: {credential_error}"
            )
        except TransmissionConnectError as daemon_error:
            raise TrackerClientError(f"Transmission daemon error: {daemon_error}")
        except TransmissionTimeoutError as timeout_error:
            raise TrackerClientError(
                f"Timed out while trying to connect to Transmission: {timeout_error}"
            )
        except Exception as e:
            raise TrackerClientError(
                f"Unexpected Error initializing Transmission client: {e}"
            )

    def inject_torrent(self, torrent_path: Path) -> tuple[bool, str]:
        try:
            add_torrent = self.client.add_torrent(
                torrent=torrent_path,
                download_dir=self._get_save_directory(),
                labels=self._get_label(),
            )
            if add_torrent and add_torrent.hash_string:
                return True, "Transmission injection successful"
            else:
                return False, "Transmission injection failed"
        except TransmissionError as communication_error:
            raise TrackerClientError(
                f"Failed to communicate with Transmission: {communication_error}"
            )
        except TransmissionConnectError as daemon_error:
            raise TrackerClientError(f"Transmission daemon error: {daemon_error}")
        except TransmissionTimeoutError as timeout_error:
            raise TrackerClientError(
                f"Timed out while trying to connect to Transmission: {timeout_error}"
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
