from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import qbittorrentapi
from qbittorrentapi.exceptions import Conflict409Error
from qbittorrentapi.torrents import TorrentsAddedMetadata

from nfoforge.backend.torrent_clients.qbittorrent import QBittorrentClient
from nfoforge.backend.torrent_clients.qbittorrent.save_path import (
    get_qbittorrent_save_path_warning,
)
from nfoforge.enums.torrent_client import QBittorrentAuthMode, QBittorrentSavePathMode
from nfoforge.exceptions import TrackerClientError
from nfoforge.payloads.clients import QBittorrentConfig


def _config(super_seeding: bool = False) -> QBittorrentConfig:
    return QBittorrentConfig(
        host="http://127.0.0.1",
        port=8080,
        user="user",
        password="password",  # noqa: S106 - dummy test fixture credential for a mocked client, not a real secret
        category="Movies",
        super_seeding=super_seeding,
        save_path_mode=QBittorrentSavePathMode.CLIENT_DEFAULT,
    )


def _api_key_config() -> QBittorrentConfig:
    return QBittorrentConfig(
        host="http://127.0.0.1",
        port=8080,
        category="Movies",
        save_path_mode=QBittorrentSavePathMode.CLIENT_DEFAULT,
        auth_mode=QBittorrentAuthMode.API_KEY,
        # qBittorrent generates `qbt_` plus 28 characters.
        api_key="qbt_" + "x" * 28,
    )


def _added(count: int = 1) -> TorrentsAddedMetadata:
    """What Web API 2.15 answers an add with.

    qBittorrent 5.2.0 replaced the "Ok."/"Fails." string with a JSON
    summary, and qbittorrent-api parses it, so `torrents_add` hands back a
    mapping. The three string mocks below are kept rather than converted:
    they pin the older clients, which still answer the old way.
    """
    return TorrentsAddedMetadata(
        {
            "success_count": count,
            "failure_count": 0,
            "pending_count": 0,
            "added_torrent_ids": ["0" * 40] * count,
        }
    )


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_inject_without_save_path_keeps_automatic_management(
    qbit_api: MagicMock,
) -> None:
    api = qbit_api.return_value
    api.torrents_add.return_value = "Ok."
    client = QBittorrentClient(_config())

    assert client.inject_torrent(Path("release.torrent")) == (
        True,
        "qBittorrent injection successful",
    )

    api.torrents_add.assert_called_once_with(
        torrent_files="release.torrent",
        save_path=None,
        use_auto_torrent_management=True,
        is_skip_checking=True,
        category="Movies",
        requests_args={"timeout": client.timeout},
    )


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_inject_with_save_path_uses_manual_management_and_preserves_path(
    qbit_api: MagicMock,
) -> None:
    api = qbit_api.return_value
    api.torrents_add.return_value = "Ok."
    client = QBittorrentClient(_config())
    save_path = r"\\plex_server\movies\Cleaner (2025)"

    assert client.inject_torrent(Path("release.torrent"), save_path) == (
        True,
        "qBittorrent injection successful",
    )

    api.torrents_add.assert_called_once_with(
        torrent_files="release.torrent",
        save_path=save_path,
        use_auto_torrent_management=False,
        is_skip_checking=False,
        category="Movies",
        requests_args={"timeout": client.timeout},
    )


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_blank_save_path_keeps_automatic_management(qbit_api: MagicMock) -> None:
    api = qbit_api.return_value
    api.torrents_add.return_value = "Ok."
    client = QBittorrentClient(_config())

    assert client.inject_torrent(Path("release.torrent"), "   ")[0] is True

    assert api.torrents_add.call_args.kwargs["save_path"] is None
    assert api.torrents_add.call_args.kwargs["use_auto_torrent_management"] is True


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_inject_accepts_the_json_answer_from_web_api_2_15(
    qbit_api: MagicMock,
) -> None:
    """The 5.2.x add, which used to be read as a failure.

    `add_torrent != "Ok."` cannot be false for a mapping, so a torrent that
    was added reported "qBittorrent injection failed" -- and returned before
    super seeding on the way out.
    """
    api = qbit_api.return_value
    api.torrents_add.return_value = _added()
    client = QBittorrentClient(_config())

    assert client.inject_torrent(Path("release.torrent")) == (
        True,
        "qBittorrent injection successful",
    )


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.Torrent")
@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_super_seeding_still_runs_after_a_json_answer(
    qbit_api: MagicMock, torrent: MagicMock
) -> None:
    # The half of the same defect that was silent: the early return took
    # super seeding with it, so the setting was ignored rather than reported.
    api = qbit_api.return_value
    api.torrents_add.return_value = _added()
    torrent.read.return_value = MagicMock(infohash="a" * 40)
    client = QBittorrentClient(_config(super_seeding=True))

    assert client.inject_torrent(Path("release.torrent"))[0] is True

    assert api.torrents_set_super_seeding.call_args.kwargs["torrent_hashes"] == "a" * 40


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_an_add_that_lands_nothing_is_a_soft_failure(qbit_api: MagicMock) -> None:
    """A 409 is 2.15's "nothing was added", most often a duplicate.

    The older clients answered that with `Fails.` and HTTP 200, which this
    adapter turned into a `False` result. Left to the APIError handler it
    became a `TrackerClientError` carrying the library's own message, so a
    second injection of the same torrent went from a reported failure to a
    raised one.
    """
    api = qbit_api.return_value
    api.torrents_add.side_effect = Conflict409Error()
    client = QBittorrentClient(_config())

    added, message = client.inject_torrent(Path("release.torrent"))

    assert added is False
    assert "already in the client" in message


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_the_older_string_verdict_is_still_read(qbit_api: MagicMock) -> None:
    # Web API 2.14 and below. Only the string form carries a verdict, and it
    # still has to be honoured -- ignoring every non-"Ok." answer would make
    # the widening above a pass-through.
    api = qbit_api.return_value
    api.torrents_add.return_value = "Fails."
    client = QBittorrentClient(_config())

    assert client.inject_torrent(Path("release.torrent")) == (
        False,
        "qBittorrent injection failed",
    )


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_qbittorrent_rejects_blank_host(qbit_api: MagicMock) -> None:
    config = _config()
    config.host = "  "

    with pytest.raises(TrackerClientError, match="Hostname must be defined"):
        QBittorrentClient(config)

    qbit_api.assert_not_called()


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_user_pass_mode_sends_credentials_and_no_api_key(qbit_api: MagicMock) -> None:
    QBittorrentClient(_config())

    qbit_api.assert_called_once_with(
        host="http://127.0.0.1",
        port=8080,
        username="user",
        password="password",  # noqa: S106 - mirrors the dummy fixture credential
    )


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_api_key_mode_sends_the_key_and_no_credentials(qbit_api: MagicMock) -> None:
    # The two are alternatives. A username sent alongside the key would be
    # dead weight at best; qBittorrent answers `auth/login` with 403 once a
    # bearer token is in play, so the library skips the login entirely.
    QBittorrentClient(_api_key_config())

    qbit_api.assert_called_once_with(
        host="http://127.0.0.1",
        port=8080,
        api_key="qbt_" + "x" * 28,
    )


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_api_key_mode_rejects_a_blank_key(qbit_api: MagicMock) -> None:
    config = _api_key_config()
    config.api_key = "  "

    with pytest.raises(TrackerClientError, match="API key must be defined"):
        QBittorrentClient(config)

    qbit_api.assert_not_called()


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_api_key_login_failure_names_the_api_key(qbit_api: MagicMock) -> None:
    api = qbit_api.return_value
    api.auth_log_in.side_effect = qbittorrentapi.LoginFailed("nope")
    client = QBittorrentClient(_api_key_config())

    success, message = client.login()

    assert not success
    assert "API key" in message
    assert "username" not in message
    # The version endpoint needs a session, so a failed login cannot tell a
    # wrong key from a client too old to have keys. Name both.
    assert "5.2.0" in message


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_an_api_key_accepted_by_a_client_too_old_for_keys_is_refused(
    qbit_api: MagicMock,
) -> None:
    # qBittorrent below 5.2.0 ignores the bearer header. With authentication
    # switched off for the calling address it then answers as though the key
    # were accepted, and nothing on screen says the connection is anonymous.
    api = qbit_api.return_value
    api.app_web_api_version.return_value = "2.13.1"
    client = QBittorrentClient(_api_key_config())

    success, message = client.login()

    assert not success
    assert "2.13.1" in message
    assert "2.14.1" in message
    assert "5.2.0" in message


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_the_first_web_api_version_with_key_support_is_accepted(
    qbit_api: MagicMock,
) -> None:
    api = qbit_api.return_value
    api.app_web_api_version.return_value = "2.14.1"
    client = QBittorrentClient(_api_key_config())

    assert client.login() == (True, "Login successful")


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_a_two_part_web_api_version_compares_correctly(qbit_api: MagicMock) -> None:
    # qBittorrent publishes both "2.15" and "2.14.1"; a string compare would
    # read the shorter one as the older.
    api = qbit_api.return_value
    api.app_web_api_version.return_value = "2.15"
    client = QBittorrentClient(_api_key_config())

    assert client.login() == (True, "Login successful")


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_an_unreadable_web_api_version_does_not_block_a_login(
    qbit_api: MagicMock,
) -> None:
    # The version is a diagnostic, not the job. A client that will not report
    # it must not be refused on that alone.
    api = qbit_api.return_value
    api.app_web_api_version.side_effect = RuntimeError("no answer")
    client = QBittorrentClient(_api_key_config())

    assert client.login() == (True, "Login successful")


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_user_pass_login_does_not_read_the_web_api_version(
    qbit_api: MagicMock,
) -> None:
    api = qbit_api.return_value
    client = QBittorrentClient(_config())

    assert client.login() == (True, "Login successful")
    api.app_web_api_version.assert_not_called()


@patch("nfoforge.backend.torrent_clients.qbittorrent.client.QBitClient")
def test_test_reports_why_the_login_failed(qbit_api: MagicMock) -> None:
    # `test` is wired to the Test button, and reporting a bare "Failed" left
    # the reason in a return value nothing read.
    api = qbit_api.return_value
    api.auth_log_in.side_effect = qbittorrentapi.LoginFailed("nope")
    client = QBittorrentClient(_config())

    success, message = client.test()

    assert not success
    assert "Check username and password" in message


def test_remote_qbittorrent_warns_for_windows_drive_path() -> None:
    warning = get_qbittorrent_save_path_warning(
        "https://seedbox.example",
        r"C:\Media\Movies",
    )

    assert warning is not None
    assert "remote" in warning


def test_local_qbittorrent_allows_windows_drive_path() -> None:
    assert (
        get_qbittorrent_save_path_warning(
            "http://127.0.0.1:8080",
            r"C:\Media\Movies",
        )
        is None
    )


def test_remote_qbittorrent_warns_for_unc_path() -> None:
    """A UNC root still gets a reachability reminder, distinct from the
    "likely mistake" wording used for a host-specific drive letter."""
    warning = get_qbittorrent_save_path_warning(
        "https://seedbox.example",
        r"\\nas\movies",
    )

    assert warning is not None


def test_local_qbittorrent_allows_unc_path() -> None:
    assert (
        get_qbittorrent_save_path_warning(
            "http://127.0.0.1:8080",
            r"\\nas\movies",
        )
        is None
    )
