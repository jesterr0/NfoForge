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
