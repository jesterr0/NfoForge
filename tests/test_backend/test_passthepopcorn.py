from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.trackers.passthepopcorn import PTPUploader
from src.enums.media_type import MediaType
from src.exceptions import TrackerError
from src.packages.custom_types import ImageUploadData
from src.payloads.media_search import MediaSearchPayload
from src.plugins.api import MetadataMediaKind


def _uploader(cookie_dir: Path, mediainfo_obj: MagicMock | None = None) -> PTPUploader:
    return PTPUploader(
        username="user",
        password="password",  # noqa: S106 - dummy test fixture credential for a mocked client, not a real secret
        mediainfo_obj=mediainfo_obj or MagicMock(),
        announce_url="https://tracker.example/announce",
        cookie_dir=cookie_dir,
    )


@patch("src.backend.trackers.passthepopcorn.ImageBoxUploader")
@patch("src.backend.trackers.passthepopcorn.niquests.get")
def test_ptp_new_group_poster_is_rehosted_on_imgbox(
    get: MagicMock, image_box_uploader: MagicMock, tmp_path: Path
) -> None:
    response = MagicMock()
    response.content = b"poster"
    get.return_value = response
    image_box_uploader.return_value.upload = AsyncMock(
        return_value={
            0: ImageUploadData("https://images2.imgbox.com/example/poster.jpg", None)
        }
    )

    result = _uploader(tmp_path)._upload_poster_to_imgbox(
        "https://image.tmdb.org/t/p/original/poster.jpg"
    )

    assert result == "https://images2.imgbox.com/example/poster.jpg"
    get.assert_called_once_with(
        "https://image.tmdb.org/t/p/original/poster.jpg", timeout=60
    )
    response.raise_for_status.assert_called_once_with()
    image_box_uploader.return_value.upload.assert_awaited_once()


@patch("src.backend.trackers.passthepopcorn.ImageBoxUploader")
@patch("src.backend.trackers.passthepopcorn.niquests.get")
def test_ptp_new_group_poster_requires_imgbox_url(
    get: MagicMock, image_box_uploader: MagicMock, tmp_path: Path
) -> None:
    response = MagicMock()
    response.content = b"poster"
    get.return_value = response
    image_box_uploader.return_value.upload = AsyncMock(
        return_value={0: ImageUploadData(None, None)}
    )

    with pytest.raises(TrackerError, match="ImageBox did not return a URL"):
        _uploader(tmp_path)._upload_poster_to_imgbox(
            "https://image.tmdb.org/t/p/original/poster.jpg"
        )


@patch("src.backend.trackers.passthepopcorn.VideoResolutionAnalyzer")
def test_ptp_upload_post_has_a_timeout(
    _resolution_analyzer: MagicMock, tmp_path: Path
) -> None:
    """Every other request in this module passes ``self.timeout`` and the
    session sets no default; a hung upload POST must not be able to block
    the worker thread forever."""
    uploader = _uploader(tmp_path)
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"torrent contents")

    fake_response = MagicMock(text="", url=None, status_code=None)
    fake_session = MagicMock()
    fake_session.post.return_value = fake_response
    uploader._session = fake_session

    media_search_payload = MagicMock()
    # Skip the type-detection duration lookup, which needs a real MediaInfo
    # object; only the timeout on the POST is under test here.
    media_search_payload.media_type = MediaType.MOVIE

    with pytest.raises(TrackerError, match="is not the expected one"):
        uploader.upload(
            auth_token="token",  # noqa: S106 - dummy test fixture auth token, not a real secret
            media_search_payload=media_search_payload,
            torrent_file=torrent_file,
            input_path=tmp_path / "Example.2026.1080p.WEB-DL-GRP",
            nfo="nfo contents",
            group_id="12345",
        )

    fake_session.post.assert_called_once()
    assert fake_session.post.call_args.kwargs["timeout"] == uploader.timeout


@patch("src.backend.trackers.passthepopcorn.VideoResolutionAnalyzer")
def test_ptp_upload_does_not_close_the_shared_session(
    _resolution_analyzer: MagicMock, tmp_path: Path
) -> None:
    """``PTPUploader`` is built once per ``ptp_uploader()`` call and
    ``login()`` runs on the same instance before ``upload()``; both share
    ``self._session``. ``upload()`` must not close it -- doing so would
    make the object usable for exactly one upload, undocumented, and would
    break any caller that reuses the instance (e.g. for a retry) after a
    failed upload."""
    uploader = _uploader(tmp_path)
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"torrent contents")

    # Use the real `niquests.Session` created by `PTPUploader.__init__` --
    # only the network call and `close()` are stubbed -- so `__exit__`
    # closing the session (the actual bug) would be caught here even though
    # a MagicMock session would not exhibit it.
    fake_response = MagicMock(text="", url=None, status_code=None)
    post = MagicMock(return_value=fake_response)
    close = MagicMock()
    uploader._session.post = post
    uploader._session.close = close

    media_search_payload = MagicMock()
    media_search_payload.media_type = MediaType.MOVIE

    with pytest.raises(TrackerError, match="is not the expected one"):
        uploader.upload(
            auth_token="token",  # noqa: S106 - dummy test fixture auth token, not a real secret
            media_search_payload=media_search_payload,
            torrent_file=torrent_file,
            input_path=tmp_path / "Example.2026.1080p.WEB-DL-GRP",
            nfo="nfo contents",
            group_id="12345",
        )

    post.assert_called_once()
    close.assert_not_called()
    # The session object itself must still be the one created in __init__
    # (not replaced or torn down), so a second call could reuse it.
    assert uploader._session.post is post


def test_ptp_2fa_uses_interactive_prompt_after_automatic_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploader = _uploader(tmp_path)
    first_response = MagicMock(status_code=200, reason="OK")
    second_response = MagicMock(status_code=200, reason="OK")
    fake_session = MagicMock()
    fake_session.post.side_effect = [first_response, second_response]
    uploader._session = fake_session

    totp = MagicMock()
    totp.now.return_value = "123456"
    monkeypatch.setattr(
        "src.backend.trackers.passthepopcorn.pyotp.TOTP", lambda _secret: totp
    )
    monkeypatch.setattr(
        "src.backend.trackers.passthepopcorn.ask_thread_safe_prompt",
        lambda *_args: (True, "654321"),
    )

    data = {"username": "user", "password": "password"}
    response, tried_totp = uploader._handle_2fa(data, "secret", False)
    assert response is first_response
    assert tried_totp
    assert data["TfaCode"] == "123456"

    response, tried_totp = uploader._handle_2fa(data, "secret", tried_totp)
    assert response is second_response
    assert tried_totp
    assert data["TfaCode"] == "654321"
    assert fake_session.post.call_args.kwargs["timeout"] == uploader.timeout


def test_ptp_2fa_attempts_are_bounded_and_backed_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploader = _uploader(tmp_path)
    uploader.totp = "secret"
    initial_response = MagicMock(
        ok=True,
        status_code=200,
        json=lambda: {"Result": "TfaRequired"},
    )
    failed_responses = [
        MagicMock(status_code=200, json=lambda: {})
        for _ in range(uploader._MAX_2FA_ATTEMPTS)
    ]
    initial_context = MagicMock()
    initial_context.__enter__.return_value = initial_response
    initial_context.__exit__.return_value = False
    fake_session = MagicMock()
    fake_session.post.side_effect = [initial_context, *failed_responses]
    uploader._session = fake_session

    monkeypatch.setattr(
        "src.backend.trackers.passthepopcorn.pyotp.TOTP",
        lambda _secret: MagicMock(now=lambda: "123456"),
    )
    monkeypatch.setattr(
        "src.backend.trackers.passthepopcorn.ask_thread_safe_prompt",
        lambda *_args: (True, "654321"),
    )
    sleeps: list[float] = []
    monkeypatch.setattr("src.backend.trackers.passthepopcorn.time.sleep", sleeps.append)

    with pytest.raises(TrackerError, match="2FA failed after 3 attempts"):
        uploader.login()

    assert fake_session.post.call_count == 1 + uploader._MAX_2FA_ATTEMPTS
    assert sleeps == [0.5, 1.0]


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (MetadataMediaKind.SHORT, "Short Film"),
        (MetadataMediaKind.MINI_SERIES, "Miniseries"),
        (MetadataMediaKind.STAND_UP_COMEDY, "Stand-up Comedy"),
        (MetadataMediaKind.LIVE_PERFORMANCE, "Live Performance"),
    ],
)
def test_ptp_type_prefers_provider_kind(
    kind: MetadataMediaKind, expected: str, tmp_path: Path
) -> None:
    payload = MediaSearchPayload(media_type=MediaType.MOVIE)
    payload.media_kind = kind

    assert _uploader(tmp_path)._get_type(payload) == expected


def test_ptp_type_uses_runtime_when_provider_has_no_specific_kind(
    tmp_path: Path,
) -> None:
    mediainfo_obj = MagicMock()
    mediainfo_obj.general_tracks = [MagicMock(duration=44 * 60_000)]
    uploader = _uploader(tmp_path, mediainfo_obj)
    payload = MediaSearchPayload(media_type=MediaType.MOVIE)
    payload.media_kind = MetadataMediaKind.MOVIE

    assert uploader._get_type(payload) == "Short Film"

    mediainfo_obj.general_tracks = [MagicMock(duration=45 * 60_000)]
    assert uploader._get_type(payload) == "Feature Film"


def test_ptp_type_uses_miniseries_for_series_without_provider_kind(
    tmp_path: Path,
) -> None:
    payload = MediaSearchPayload(media_type=MediaType.SERIES)

    assert _uploader(tmp_path)._get_type(payload) == "Miniseries"
