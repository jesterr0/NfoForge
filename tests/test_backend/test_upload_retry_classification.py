from pathlib import Path
from unittest.mock import MagicMock, patch

import niquests
import pytest

from src.backend.process import ProcessBackEnd
from src.backend.trackers.huno import HunoUploader
from src.backend.upload_retry import classify_upload_post_error
from src.enums.media_type import MediaType
from src.exceptions import TrackerError


@pytest.mark.parametrize(
    ("error", "expected"),
    (
        # Nothing was transmitted: safe to re-POST automatically.
        (niquests.exceptions.ConnectTimeout("connect timed out"), (True, False)),
        (niquests.exceptions.ConnectionError("connection refused"), (True, False)),
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
    assert issubclass(niquests.exceptions.ConnectTimeout, niquests.exceptions.ConnectionError)
    assert classify_upload_post_error(niquests.exceptions.ConnectTimeout("x")) == (True, False)


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
