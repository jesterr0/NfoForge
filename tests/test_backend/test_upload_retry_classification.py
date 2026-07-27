from pathlib import Path
from unittest.mock import MagicMock, patch

import niquests
import pytest

from src.backend.process import ProcessBackEnd
from src.backend.trackers.beyondhd import BHDUploader
from src.backend.trackers.huno import HunoUploader
from src.backend.trackers.torrentleech import TLUploader
from src.backend.upload_retry import classify_upload_post_error, scrub_secrets
from src.enums.media_type import MediaType
from src.exceptions import TrackerError


@pytest.mark.parametrize(
    ("error", "expected"),
    (
        # Nothing was transmitted: safe to re-POST automatically.
        (niquests.exceptions.ConnectTimeout("connect timed out"), (True, False)),
        # A bare ConnectionError is NOT provably pre-body: niquests wraps the
        # whole send-body-and-read-headers span in one except clause, so a
        # reset while the tracker was processing an already-received upload
        # looks identical to a refused connection. Must route to the user.
        (niquests.exceptions.ConnectionError("connection refused"), (None, True)),
        # The body was fully sent; the tracker may have recorded the upload.
        (niquests.exceptions.ReadTimeout("read timed out"), (True, True)),
        (
            niquests.exceptions.JSONDecodeError("Expecting value", "<html>", 0),
            (True, True),
        ),
        (niquests.exceptions.InvalidJSONError("bad json"), (True, True)),
        # Unknown transport failures are assumed to have reached the tracker.
        (niquests.exceptions.RequestException("something else"), (None, True)),
        (niquests.exceptions.TooManyRedirects("too many redirects"), (None, True)),
    ),
)
def test_classify_upload_post_error(
    error: BaseException, expected: tuple[bool | None, bool]
) -> None:
    assert classify_upload_post_error(error) == expected


def test_connect_timeout_is_checked_before_connection_error() -> None:
    """ConnectTimeout subclasses ConnectionError; ordering must not misclassify it."""
    assert issubclass(
        niquests.exceptions.ConnectTimeout, niquests.exceptions.ConnectionError
    )
    assert classify_upload_post_error(niquests.exceptions.ConnectTimeout("x")) == (
        True,
        False,
    )


def test_bare_connection_error_is_not_retried_automatically() -> None:
    """Regression test for treating a bare ConnectionError as pre-body.

    Verified against niquests' HTTPAdapter.send (adapters.py): the whole
    ``conn.urlopen(..., preload_content=False)`` call -- which spans sending
    the multipart body and reading the response headers -- is wrapped in a
    single ``except (ProtocolError, OSError) as err: raise
    ConnectionError(err, request=request)``. A tracker that accepted a large
    upload and then reset while processing it is indistinguishable, from
    this exception alone, from a connection that was refused outright.
    """
    retryable, server_accepted = classify_upload_post_error(
        niquests.exceptions.ConnectionError("connection reset by peer")
    )
    assert retryable is None
    assert server_accepted is True
    error = TrackerError(
        "connection reset", retryable=retryable, server_accepted=server_accepted
    )
    assert ProcessBackEnd._is_automatic_upload_retryable(error) is False


def test_json_decode_error_is_a_request_exception() -> None:
    """The bug this classifier fixes: a non-JSON response body looks like a transport error."""
    assert issubclass(
        niquests.exceptions.JSONDecodeError, niquests.exceptions.RequestException
    )


def _uploader(torrent_file: Path) -> HunoUploader:
    return HunoUploader(
        media_type=MediaType.MOVIE,
        api_key="api-key",
        torrent_file=torrent_file,
        input_path=torrent_file.parent / "Example.2026.1080p.WEB-DL-GRP",
        mediainfo_obj=MagicMock(),
    )


def _upload_raising(post_error: BaseException, tmp_path: Path) -> TrackerError:
    """Run a real upload with the POST failing, and return the TrackerError."""
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"original torrent")
    # The uploader classes use __slots__, so stub on the class, not the instance.
    with (
        patch.object(HunoUploader, "_build_upload_payload", return_value={}),
        patch("src.backend.trackers.unit3d_base.niquests.post") as post,
    ):
        post.side_effect = post_error
        with pytest.raises(TrackerError) as excinfo:
            _uploader(torrent_file).upload(
                tracker_title="Example.2026.1080p.WEB-DL-GRP"
            )
    return excinfo.value


def test_read_timeout_on_upload_is_not_retried_automatically(tmp_path: Path) -> None:
    """A timed-out POST may already have been accepted; it must reach the user."""
    error = _upload_raising(niquests.exceptions.ReadTimeout("read timed out"), tmp_path)

    assert error.server_accepted is True
    assert ProcessBackEnd._is_automatic_upload_retryable(error) is False


def test_html_error_page_on_upload_is_not_retried_automatically(tmp_path: Path) -> None:
    error = _upload_raising(
        niquests.exceptions.JSONDecodeError("Expecting value", "<html>", 0), tmp_path
    )

    assert error.server_accepted is True
    assert ProcessBackEnd._is_automatic_upload_retryable(error) is False


def test_connect_timeout_on_upload_is_still_retried_automatically(
    tmp_path: Path,
) -> None:
    """Nothing left the socket, so the automatic retry budget still applies."""
    error = _upload_raising(
        niquests.exceptions.ConnectTimeout("connect timed out"), tmp_path
    )

    assert error.server_accepted is False
    assert ProcessBackEnd._is_automatic_upload_retryable(error) is True


def _upload_raising_from_response(
    response_json: dict[str, object], status_code: int, tmp_path: Path
) -> TrackerError:
    """Run a real UNIT3D upload where the tracker responds with a structured failure."""
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"original torrent")
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    mock_response.json.return_value = response_json
    mock_response.status_code = status_code
    with (
        patch.object(HunoUploader, "_build_upload_payload", return_value={}),
        patch(
            "src.backend.trackers.unit3d_base.niquests.post",
            return_value=mock_response,
        ),
    ):
        with pytest.raises(TrackerError) as excinfo:
            _uploader(torrent_file).upload(
                tracker_title="Example.2026.1080p.WEB-DL-GRP"
            )
    return excinfo.value


def test_unit3d_408_response_is_retryable(tmp_path: Path) -> None:
    """A structured 408 from a UNIT3D tracker must agree with the generic rule."""
    error = _upload_raising_from_response(
        {"success": False, "message": "Rate limited", "data": None}, 408, tmp_path
    )

    assert error.status_code == 408
    assert error.retryable is True
    assert ProcessBackEnd._is_automatic_upload_retryable(error) is True


def test_unit3d_429_response_is_retryable(tmp_path: Path) -> None:
    """A structured 429 from a UNIT3D tracker must remain automatically retryable."""
    error = _upload_raising_from_response(
        {"success": False, "message": "Rate limited", "data": None}, 429, tmp_path
    )

    assert error.status_code == 429
    assert error.retryable is True
    assert error.server_accepted is False
    assert ProcessBackEnd._is_automatic_upload_retryable(error) is True


def test_unit3d_5xx_response_is_not_retried_automatically(tmp_path: Path) -> None:
    """A 5xx means UNIT3D received and answered the upload; it must not
    auto-retry and must route to the user instead."""
    error = _upload_raising_from_response(
        {"success": False, "message": "Internal error", "data": None}, 500, tmp_path
    )

    assert error.status_code == 500
    assert error.server_accepted is True
    assert ProcessBackEnd._is_automatic_upload_retryable(error) is False


def test_beyondhd_408_response_is_retryable(tmp_path: Path) -> None:
    """A structured 408 from BeyondHD must agree with the generic status-code rule."""
    uploader = BHDUploader(
        api_key="api-key",
        torrent_file=tmp_path / "release.torrent",
        input_path=tmp_path / "Example.2026.1080p.WEB-DL-GRP",
        media_type=MediaType.MOVIE,
    )
    mock_response = MagicMock(ok=False, status_code=408, reason="Request Timeout")
    with (
        patch.object(BHDUploader, "_build_upload_payload", return_value={}),
        patch.object(BHDUploader, "_files", return_value={}),
        patch(
            "src.backend.trackers.beyondhd.niquests.post", return_value=mock_response
        ),
    ):
        with pytest.raises(TrackerError) as excinfo:
            uploader.upload(tracker_title="Example.2026.1080p.WEB-DL-GRP")

    error = excinfo.value
    assert error.status_code == 408
    assert error.retryable is True
    assert ProcessBackEnd._is_automatic_upload_retryable(error) is True


def _bhd_upload_raising(status_code: int, tmp_path: Path) -> TrackerError:
    uploader = BHDUploader(
        api_key="api-key",
        torrent_file=tmp_path / "release.torrent",
        input_path=tmp_path / "Example.2026.1080p.WEB-DL-GRP",
        media_type=MediaType.MOVIE,
    )
    mock_response = MagicMock(ok=False, status_code=status_code, reason="error")
    with (
        patch.object(BHDUploader, "_build_upload_payload", return_value={}),
        patch.object(BHDUploader, "_files", return_value={}),
        patch(
            "src.backend.trackers.beyondhd.niquests.post", return_value=mock_response
        ),
    ):
        with pytest.raises(TrackerError) as excinfo:
            uploader.upload(tracker_title="Example.2026.1080p.WEB-DL-GRP")
    return excinfo.value


def test_beyondhd_429_response_is_retryable(tmp_path: Path) -> None:
    """A structured 429 from BeyondHD must remain automatically retryable."""
    error = _bhd_upload_raising(429, tmp_path)

    assert error.status_code == 429
    assert error.retryable is True
    assert error.server_accepted is False
    assert ProcessBackEnd._is_automatic_upload_retryable(error) is True


def test_beyondhd_5xx_response_is_not_retried_automatically(tmp_path: Path) -> None:
    """A 5xx means BeyondHD received and answered the upload; it must not
    auto-retry and must route to the user instead."""
    error = _bhd_upload_raising(502, tmp_path)

    assert error.status_code == 502
    assert error.server_accepted is True
    assert ProcessBackEnd._is_automatic_upload_retryable(error) is False


def test_torrentleech_408_response_is_retryable(tmp_path: Path) -> None:
    """A structured 408 from TorrentLeech must agree with the generic status-code rule."""
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"original torrent")
    uploader = TLUploader(announce_key="key")
    mock_response = MagicMock(
        ok=False, status_code=408, reason="Request Timeout", text="body"
    )
    with (
        patch.object(TLUploader, "_get_data", return_value={}),
        patch("src.backend.trackers.torrentleech.VideoResolutionAnalyzer"),
        patch(
            "src.backend.trackers.torrentleech.niquests.post",
            return_value=mock_response,
        ),
    ):
        with pytest.raises(TrackerError) as excinfo:
            uploader.upload(
                nfo="nfo contents",
                tracker_title=None,
                torrent_file=torrent_file,
                mediainfo_obj=MagicMock(),
                media_type=MediaType.MOVIE,
                is_pack=False,
            )

    error = excinfo.value
    assert error.status_code == 408
    assert error.retryable is True
    assert ProcessBackEnd._is_automatic_upload_retryable(error) is True


def _tl_upload_raising(status_code: int, tmp_path: Path) -> TrackerError:
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"original torrent")
    uploader = TLUploader(announce_key="key")
    mock_response = MagicMock(
        ok=False, status_code=status_code, reason="error", text="body"
    )
    with (
        patch.object(TLUploader, "_get_data", return_value={}),
        patch("src.backend.trackers.torrentleech.VideoResolutionAnalyzer"),
        patch(
            "src.backend.trackers.torrentleech.niquests.post",
            return_value=mock_response,
        ),
    ):
        with pytest.raises(TrackerError) as excinfo:
            uploader.upload(
                nfo="nfo contents",
                tracker_title=None,
                torrent_file=torrent_file,
                mediainfo_obj=MagicMock(),
                media_type=MediaType.MOVIE,
                is_pack=False,
            )
    return excinfo.value


def test_torrentleech_429_response_is_retryable(tmp_path: Path) -> None:
    """A structured 429 from TorrentLeech must remain automatically retryable."""
    error = _tl_upload_raising(429, tmp_path)

    assert error.status_code == 429
    assert error.retryable is True
    assert error.server_accepted is False
    assert ProcessBackEnd._is_automatic_upload_retryable(error) is True


def test_torrentleech_5xx_response_is_not_retried_automatically(tmp_path: Path) -> None:
    """A 5xx means TorrentLeech received and answered the upload; it must not
    auto-retry and must route to the user instead.

    Pre-branch, TorrentLeech's message text only matched an old "service
    unavailable" marker, so 500/502/504 did not auto-retry. This branch's
    status-code annotation widened that to retry every 5xx automatically;
    this test locks the safe behaviour back in.
    """
    error = _tl_upload_raising(500, tmp_path)

    assert error.status_code == 500
    assert error.server_accepted is True
    assert ProcessBackEnd._is_automatic_upload_retryable(error) is False


def test_unannotated_error_is_not_retried_automatically() -> None:
    """With every tracker annotated, an unknown error must not be guessed at."""
    assert ProcessBackEnd._is_automatic_upload_retryable(TrackerError("boom")) is False


def test_error_text_no_longer_drives_retry_decisions() -> None:
    """An un-annotated error containing 'timeout' must not be guessed retryable.

    ``retryable`` and ``status_code`` are both left unset, so this is the only
    construction that actually reaches the code path the marker list used to
    occupy; a substring match on "gateway timeout advice" would have flipped
    the old heuristic to retryable.
    """
    error = TrackerError(
        "There was an error uploading to TorrentLeech: 403 "
        "(Forbidden - <html><body>gateway timeout advice</body></html>)",
    )

    assert ProcessBackEnd._is_automatic_upload_retryable(error) is False


def test_status_code_still_drives_retry_when_retryable_is_unset() -> None:
    """A 5xx means the tracker answered the request; it may have recorded
    the upload before failing, so the status-code fallback must not treat
    it as automatically retryable."""
    assert (
        ProcessBackEnd._is_automatic_upload_retryable(
            TrackerError("server error", status_code=503)
        )
        is False
    )
    assert (
        ProcessBackEnd._is_automatic_upload_retryable(
            TrackerError("forbidden", status_code=403)
        )
        is False
    )


def test_http_408_is_retryable_via_status_code() -> None:
    """A 408 means the request body never fully arrived, so retrying is safe."""
    assert (
        ProcessBackEnd._is_automatic_upload_retryable(
            TrackerError("request timeout", status_code=408)
        )
        is True
    )


def test_http_429_is_retryable_via_status_code() -> None:
    """A 429 means the request was rejected before processing, so retrying is safe."""
    assert (
        ProcessBackEnd._is_automatic_upload_retryable(
            TrackerError("rate limited", status_code=429)
        )
        is True
    )


def test_http_5xx_is_not_retryable_via_status_code() -> None:
    """A 5xx means the request was received and answered; it must not be
    guessed as automatically retryable via the status-code fallback."""
    assert (
        ProcessBackEnd._is_automatic_upload_retryable(
            TrackerError("bad gateway", status_code=502)
        )
        is False
    )


def test_server_accepted_overrides_retryable() -> None:
    error = TrackerError("timed out", retryable=True, server_accepted=True)

    assert ProcessBackEnd._is_automatic_upload_retryable(error) is False


def test_scrub_secrets_redacts_query_string_credentials() -> None:
    text = (
        "Max retries exceeded with url: /api/torrents/upload?api_token=SECRETKEY123 "
        "(Caused by ReadTimeoutError)"
    )

    scrubbed = scrub_secrets(text)

    assert "SECRETKEY123" not in scrubbed
    assert "api_token=[redacted]" in scrubbed


def test_scrub_secrets_handles_several_parameter_names() -> None:
    text = "?apikey=AAA&passkey=BBB&api_key=CCC&api_token=DDD"

    scrubbed = scrub_secrets(text)

    for secret in ("AAA", "BBB", "CCC", "DDD"):
        assert secret not in scrubbed


def test_scrub_secrets_leaves_ordinary_text_alone() -> None:
    text = "Failed to upload to Aither: 503 Service Unavailable"

    assert scrub_secrets(text) == text


def test_scrub_secrets_preserves_everything_after_the_token() -> None:
    """An over-matching pattern would hide the actual error, not just the secret."""
    text = (
        "Max retries exceeded with url: "
        "/api/torrents/upload?api_token=SECRETKEY123&foo=bar "
        "(Caused by ReadTimeoutError)"
    )

    assert scrub_secrets(text) == (
        "Max retries exceeded with url: "
        "/api/torrents/upload?api_token=[redacted]&foo=bar "
        "(Caused by ReadTimeoutError)"
    )


def test_scrub_secrets_redacts_uri_userinfo_password() -> None:
    """rTorrent embeds credentials as userinfo in its host URI, and an
    xmlrpc.client.ProtocolError copies the full netloc into its message
    (verified: ``str(ProtocolError(url, ...))`` includes ``self.url``
    verbatim). The password must be redacted; the username may stay."""
    text = (
        "<ProtocolError for https://myuser:hunter2@tracker.example/rpc: "
        "500 Internal Server Error>"
    )

    scrubbed = scrub_secrets(text)

    assert "hunter2" not in scrubbed
    assert "myuser" in scrubbed
    assert "https://myuser:[redacted]@tracker.example/rpc" in scrubbed


def test_scrub_secrets_leaves_plain_uri_without_credentials_alone() -> None:
    text = "Failed to reach https://tracker.example/rpc: connection refused"

    assert scrub_secrets(text) == text
