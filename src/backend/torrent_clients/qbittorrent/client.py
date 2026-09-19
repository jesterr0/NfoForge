from pathlib import Path

from qbittorrentapi import Client as QBitClient
import qbittorrentapi.exceptions
from torf import Torrent

from src.backend.torrent_clients.qbittorrent.save_path import (
    get_qbittorrent_save_path_warning,
)
from src.enums.torrent_client import QBittorrentAuthMode
from src.exceptions import TrackerClientError
from src.logger.nfo_forge_logger import LOG
from src.payloads.clients import QBittorrentConfig

# Web API 2.14.1 -- qBittorrent 5.2.0 -- added `app/rotateAPIKey` and bearer
# token authentication. Compared as a tuple of ints because qBittorrent
# publishes both two- and three-part versions, and "2.15" sorts below
# "2.14.1" as a string.
_API_KEY_MIN_WEB_API_VERSION = (2, 14, 1)


class QBittorrentClient:
    """qBittorrent API adapter."""

    def __init__(self, config: QBittorrentConfig, timeout: int = 10) -> None:
        self.timeout = timeout
        self.qbit_config = config

        host = (self.qbit_config.host or "").strip()
        if not host:
            raise TrackerClientError("Hostname must be defined")

        if self._uses_api_key():
            api_key = self.qbit_config.api_key.strip()
            if not api_key:
                raise TrackerClientError("API key must be defined")
            # The key is sent as a bearer token on every request, and
            # qBittorrent answers the `auth/` endpoints with 403 once one is
            # in play. qbittorrent-api knows this: it validates the key with
            # an ordinary call instead of logging in, and makes logout a
            # no-op. So `login`/`logout` below need no second path.
            self.client = QBitClient(
                host=host,
                port=self._get_port(),
                api_key=api_key,
            )
        else:
            self.client = QBitClient(
                host=host,
                port=self._get_port(),
                username=str(self.qbit_config.user),
                password=str(self.qbit_config.password),
            )

    def login(self) -> tuple[bool, str]:
        try:
            self.client.auth_log_in(requests_args={"timeout": self.timeout})
        except qbittorrentapi.LoginFailed as error:
            if self._uses_api_key():
                # The version endpoint needs a session of its own, so a
                # refused login cannot tell a wrong key from a client with no
                # key support at all. Name both rather than pick one.
                return False, (
                    "Login failed. Check the API key, and that qBittorrent "
                    f"is 5.2.0 or above: {error}"
                )
            return False, f"Login failed. Check username and password: {error}"
        except qbittorrentapi.exceptions.APIConnectionError:
            return False, (
                "qBittorrent is not detected. Ensure that it's running and "
                "check host and port."
            )
        except Exception as error:
            raise TrackerClientError(
                f"Unexpected error during login: {error}"
            ) from error

        if self._uses_api_key():
            too_old = self._api_key_unsupported_message()
            if too_old:
                return False, too_old
        return True, "Login successful"

    def _api_key_unsupported_message(self) -> str | None:
        """Why an accepted key was not really accepted, if it was not.

        qBittorrent below 5.2.0 has no bearer-token support and ignores the
        header. When authentication is switched off for the calling address
        it then answers every request as though the key had been accepted,
        and the connection is anonymous with nothing on screen saying so.
        Reading the version is the only way to tell the two apart, and it
        needs the session the login just established.
        """
        try:
            reported = str(
                self.client.app_web_api_version(requests_args={"timeout": self.timeout})
            )
            version = tuple(int(part) for part in reported.split("."))
        except Exception:
            # A diagnostic, not the job. A client that will not report its
            # version must not be refused on that alone.
            return None
        if version >= _API_KEY_MIN_WEB_API_VERSION:
            return None
        return (
            f"qBittorrent's Web API is version {reported}, which has no API "
            "key support. Keys need Web API 2.14.1 or above, which is "
            "qBittorrent 5.2.0. This client ignored the key and accepted the "
            "connection only because authentication is off for this address. "
            "Use a username and password instead."
        )

    def logout(self) -> None:
        try:
            self.client.auth_log_out(requests_args={"timeout": self.timeout})
        except Exception as error:
            raise TrackerClientError(f"Failed to logout: {error}") from error

    def test(self) -> tuple[bool, str]:
        success, message = self.login()
        if success:
            return (
                True,
                "Login successful! If your category is setup correctly "
                "injection should work.",
            )
        # `login` is the only thing that knows why, and a bare "Failed" left
        # that reason in a return value nothing read.
        return False, message

    def inject_torrent(
        self,
        torrent_file: Path,
        save_path: str | None = None,
    ) -> tuple[bool, str]:
        try:
            effective_save_path = save_path if save_path and save_path.strip() else None
            path_warning = get_qbittorrent_save_path_warning(
                self.qbit_config.host,
                effective_save_path,
            )
            if path_warning:
                LOG.warning(LOG.LOG_SOURCE.BE, path_warning)
            try:
                add_torrent = self.client.torrents_add(
                    torrent_files=str(torrent_file),
                    save_path=effective_save_path,
                    use_auto_torrent_management=effective_save_path is None,
                    is_skip_checking=effective_save_path is None,
                    category=self._get_category(),
                    requests_args={"timeout": self.timeout},
                )
            except qbittorrentapi.exceptions.Conflict409Error:
                # What "nothing was added" became in the same release, most
                # often a torrent the client already holds. It was `Fails.`
                # with HTTP 200 before, and a soft failure here, so it stays
                # one rather than being raised at the user with the library's
                # own wording. Only the add is caught: a 409 from anything
                # else below would not mean this.
                return False, (
                    "qBittorrent injection failed; nothing was added. The "
                    "torrent is most likely already in the client."
                )
            # Web API 2.14 and below answered the add with "Ok." or
            # "Fails."; 2.15 -- qBittorrent 5.2.0, commit 7ddbf58a3 --
            # answers with a JSON summary, which qbittorrent-api hands back
            # as a mapping rather than a string. Compared against "Ok." that
            # can only fail, so a successful add was reported as a failure,
            # and the early return took super seeding out with it. Only the
            # string form still carries a verdict; on the newer clients an
            # add that lands nothing arrives as a 409 instead, caught below.
            if isinstance(add_torrent, str) and add_torrent != "Ok.":
                return False, "qBittorrent injection failed"

            if self.qbit_config.super_seeding:
                torrent = Torrent.read(torrent_file)
                self.client.torrents_set_super_seeding(
                    enable=True,
                    torrent_hashes=torrent.infohash,
                    requests_args={"timeout": self.timeout},
                )
            return True, "qBittorrent injection successful"
        except qbittorrentapi.exceptions.APIError as error:
            raise TrackerClientError(f"Failed to inject torrent: {error}") from error
        except Exception as error:
            raise TrackerClientError(
                f"Unexpected error during torrent injection: {error}"
            ) from error

    def _get_category(self) -> str:
        category = self.qbit_config.category.strip()
        if not category:
            raise TrackerClientError(
                "You must supply your category in the configuration"
            )
        return category

    def _uses_api_key(self) -> bool:
        return self.qbit_config.auth_mode is QBittorrentAuthMode.API_KEY

    def _get_port(self) -> int | None:
        port = int(self.qbit_config.port or 0)
        return port if port > 0 else None
