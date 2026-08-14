from pathlib import Path
from unittest.mock import MagicMock, patch

from src.backend.trackers.lst import LSTUploader
from src.enums.media_type import MediaType


def _uploader(tmp_path: Path) -> LSTUploader:
    video_track = MagicMock()
    video_track.width = 3840
    video_track.height = 2160
    video_track.scan_type = "Progressive"
    video_track.frame_rate = "24.000"
    media_info = MagicMock(video_tracks=[video_track])
    return LSTUploader(
        media_type=MediaType.MOVIE,
        api_key="api-key",
        torrent_file=tmp_path / "release.torrent",
        input_path=tmp_path / "Movie.2026.2160p.WEB-DL.H265-GRP.mkv",
        mediainfo_obj=media_info,
    )


@patch("src.backend.trackers.unit3d_base.MinimalMediaInfo")
def test_lst_payload_keeps_exact_freeleech_percentage(
    minimal_media_info: MagicMock, tmp_path: Path
) -> None:
    minimal_media_info.return_value.get_full_mi_str.return_value = "MediaInfo"

    payload = _uploader(tmp_path)._build_upload_payload(
        tracker_title="Movie 2026 2160p WEB-DL H265-GRP",
        tmdb_id="12345",
        nfo="Description",
        free=75,
    )

    assert payload["resolution_id"] == "2"
    assert payload["free"] == 75
