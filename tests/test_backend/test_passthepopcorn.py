from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.trackers.passthepopcorn import PTPUploader
from src.exceptions import TrackerError
from src.packages.custom_types import ImageUploadData


def _uploader(cookie_dir: Path) -> PTPUploader:
    return PTPUploader(
        username="user",
        password="password",
        mediainfo_obj=MagicMock(),
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
    fake_session.__enter__.return_value = fake_session
    fake_session.__exit__.return_value = False
    fake_session.post.return_value = fake_response
    uploader._session = fake_session

    media_search_payload = MagicMock()
    # Skip the type-detection duration lookup, which needs a real MediaInfo
    # object; only the timeout on the POST is under test here.
    media_search_payload.imdb_data.kind = None

    with pytest.raises(TrackerError, match="is not the expected one"):
        uploader.upload(
            auth_token="token",
            media_search_payload=media_search_payload,
            torrent_file=torrent_file,
            input_path=tmp_path / "Example.2026.1080p.WEB-DL-GRP",
            nfo="nfo contents",
            group_id="12345",
        )

    fake_session.post.assert_called_once()
    assert fake_session.post.call_args.kwargs["timeout"] == uploader.timeout
