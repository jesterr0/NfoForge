from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest
from tenacity.wait import wait_none

from src.backend.trackers.huno import HunoUploader
from src.backend.trackers.unit3d_base import Unit3dBaseUploader
from src.enums.media_type import MediaType
from src.exceptions import TrackerError


def _uploader(torrent_file: Path) -> HunoUploader:
    return HunoUploader(
        media_type=MediaType.MOVIE,
        api_key="api-key",
        torrent_file=torrent_file,
        input_path=torrent_file.parent / "Example.2026.1080p.WEB-DL-GRP",
        mediainfo_obj=MagicMock(),
    )


@patch("src.backend.trackers.unit3d_base.niquests.get")
def test_unit3d_download_replaces_generated_torrent_atomically(
    get: MagicMock, tmp_path: Path
) -> None:
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"original torrent")
    response = MagicMock()
    response.headers = {"Content-Type": "application/x-bittorrent"}
    response.iter_content.return_value = [b"d8:announce1:ae"]
    get.return_value.__enter__.return_value = response

    result = _uploader(torrent_file)._download_uploaded_torrent(
        "https://hawke.uno/torrents/download/123.key"
    )

    assert result == torrent_file
    assert torrent_file.read_bytes() == b"d8:announce1:ae"
    assert not list(tmp_path.glob("*.part"))
    get.assert_called_once_with(
        "https://hawke.uno/torrents/download/123.key",
        headers=ANY,
        timeout=60,
        stream=True,
    )
    response.raise_for_status.assert_called_once_with()
    response.iter_content.assert_called_once_with(chunk_size=64 * 1024)


@patch("src.backend.trackers.unit3d_base.niquests.get")
def test_unit3d_download_preserves_original_torrent_on_invalid_response(
    get: MagicMock, tmp_path: Path
) -> None:
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"original torrent")
    response = MagicMock()
    response.headers = {"Content-Type": "text/html"}
    response.iter_content.return_value = [b"<html>Access denied</html>"]
    get.return_value.__enter__.return_value = response

    with pytest.raises(TrackerError, match="not a valid torrent"):
        _uploader(torrent_file)._download_uploaded_torrent(
            "https://hawke.uno/torrents/download/123.key"
        )

    assert torrent_file.read_bytes() == b"original torrent"
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize(
    "download_url",
    [
        "ftp://hawke.uno/torrents/download/123.key",
        "file:///etc/passwd",
        "javascript:alert(1)",
    ],
)
@patch("src.backend.trackers.unit3d_base.niquests.get")
def test_unit3d_download_rejects_unsupported_scheme(
    get: MagicMock, download_url: str, tmp_path: Path
) -> None:
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"original torrent")

    with pytest.raises(TrackerError, match="unsupported scheme"):
        _uploader(torrent_file)._download_uploaded_torrent(download_url)

    get.assert_not_called()
    assert torrent_file.read_bytes() == b"original torrent"
    assert not list(tmp_path.glob("*.part"))


@patch("src.backend.trackers.unit3d_base.niquests.get")
def test_unit3d_download_rejects_mismatched_host(
    get: MagicMock, tmp_path: Path
) -> None:
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"original torrent")

    with pytest.raises(TrackerError, match="unexpected host"):
        _uploader(torrent_file)._download_uploaded_torrent(
            "https://evil.example/torrents/download/123.key"
        )

    get.assert_not_called()
    assert torrent_file.read_bytes() == b"original torrent"
    assert not list(tmp_path.glob("*.part"))


@patch.object(Unit3dBaseUploader, "_build_upload_payload", return_value={})
@patch("src.backend.trackers.unit3d_base.niquests.post")
def test_unit3d_upload_redownloads_tracker_torrent_before_success(
    post: MagicMock,
    _build_payload: MagicMock,
    tmp_path: Path,
) -> None:
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"generated torrent")
    response = MagicMock()
    response.json.return_value = {
        "success": True,
        "message": "Torrent uploaded successfully.",
        "data": "https://tracker.example/torrents/download/123.key",
    }
    post.return_value.__enter__.return_value = response
    uploader = _uploader(torrent_file)

    def replace_uploaded_torrent(_download_url: str) -> None:
        replacement = tmp_path / "replacement.torrent"
        replacement.write_bytes(b"tracker torrent")
        replacement.replace(torrent_file)

    with patch.object(
        Unit3dBaseUploader,
        "_download_uploaded_torrent",
        side_effect=replace_uploaded_torrent,
    ) as download_torrent:
        assert uploader.upload(tracker_title="Example") is True

    assert torrent_file.read_bytes() == b"tracker torrent"
    download_torrent.assert_called_once_with(
        "https://tracker.example/torrents/download/123.key"
    )


def test_unit3d_download_retry_does_not_repeat_upload_post(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "src.backend.trackers.unit3d_base.wait_exponential",
        lambda **_kwargs: wait_none(),
    )
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"original torrent")
    uploader = _uploader(torrent_file)
    download = MagicMock(
        side_effect=[
            TrackerError(
                "temporary artifact download failure",
                retryable=True,
                server_accepted=True,
                phase="download",
            ),
            torrent_file,
        ]
    )

    with patch.object(Unit3dBaseUploader, "_download_uploaded_torrent", download):
        assert (
            uploader._download_uploaded_torrent_with_retry(
                "https://tracker.example/torrents/download/123.key"
            )
            == torrent_file
        )

    assert download.call_count == 2
