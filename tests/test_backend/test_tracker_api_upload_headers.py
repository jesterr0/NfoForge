from pathlib import Path
from unittest.mock import MagicMock, patch

from src.backend.trackers.beyondhd import BHDUploader
from src.backend.trackers.utils import API_TRACKER_HEADERS, TRACKER_HEADERS
from src.enums.media_type import MediaType


def test_json_api_headers_do_not_change_browser_form_headers() -> None:
    assert API_TRACKER_HEADERS == {
        **TRACKER_HEADERS,
        "Accept": "application/json",
    }
    assert "Accept" not in TRACKER_HEADERS


@patch.object(BHDUploader, "_files", return_value={})
@patch.object(BHDUploader, "_build_upload_payload", return_value={})
@patch("src.backend.trackers.beyondhd.niquests.post")
def test_beyondhd_upload_requests_json(
    post: MagicMock,
    _build_payload: MagicMock,
    _files: MagicMock,
    tmp_path: Path,
) -> None:
    response = MagicMock(ok=True, status_code=200)
    response.json.return_value = {
        "success": True,
        "status_code": 1,
        "status_message": "draft",
    }
    post.return_value = response
    uploader = BHDUploader(
        api_key="api-key",
        torrent_file=tmp_path / "release.torrent",
        input_path=tmp_path / "Movie.2026.1080p.WEB-DL-GRP.mkv",
        media_type=MediaType.MOVIE,
    )

    assert uploader.upload(tracker_title="Movie 2026 1080p WEB-DL-GRP") == (
        "Successfully uploaded as a draft"
    )
    assert post.call_args.kwargs["headers"] == API_TRACKER_HEADERS
