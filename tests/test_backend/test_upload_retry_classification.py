import niquests
import pytest

from src.backend.upload_retry import classify_upload_post_error


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
