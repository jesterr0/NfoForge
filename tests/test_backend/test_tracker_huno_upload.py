from io import BytesIO
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

from src.backend.trackers.aither import AitherUploader
from src.backend.trackers.huno import HunoUploader
from src.backend.trackers.utils import API_TRACKER_HEADERS
from src.enums.media_type import MediaType


def _huno_uploader(tmp_path: Path) -> HunoUploader:
    return HunoUploader(
        media_type=MediaType.MOVIE,
        api_key="api-key",
        torrent_file=tmp_path / "release.torrent",
        input_path=tmp_path / "Example.2026.1080p.WEB-DL-GRP.mkv",
        mediainfo_obj=MagicMock(),
    )


def test_huno_auto_mode_uploads_description_and_mediainfo_as_txt_files(
    tmp_path: Path,
) -> None:
    uploader = _huno_uploader(tmp_path)
    torrent = BytesIO(b"torrent")
    payload = {
        "name": "A user-edited title",
        "description": "[center]description[/center]",
        "mediainfo": "General\nVideo\nAudio",
        "category_id": "1",
        "type_id": "3",
        "resolution_id": "3",
        "tmdb": "12345",
        "imdb": 1234567,
        "tvdb": 0,
        "mal": 0,
        "anonymous": 1,
        "internal": 0,
        "stream": 1,
        "sd": 0,
        "igdb": 0,
    }

    data, files = uploader._prepare_upload_request(payload, torrent)

    assert data == {
        "category_id": "1",
        "type_id": "3",
        "tmdb": "12345",
        "imdb": 1234567,
        "tvdb": 0,
        "mal": 0,
        "anonymous": 1,
        "internal": 0,
    }
    assert files == {
        "torrent": torrent,
        "description": (
            "description.txt",
            b"[center]description[/center]",
            "text/plain",
        ),
        "mediainfo": ("mediainfo.txt", b"General\nVideo\nAudio", "text/plain"),
    }
    # Request preparation must not mutate the payload retained for logging or
    # another upload attempt.
    assert payload["description"] == "[center]description[/center]"
    assert payload["mediainfo"] == "General\nVideo\nAudio"


def test_huno_season_pack_omits_episode_number(tmp_path: Path) -> None:
    uploader = _huno_uploader(tmp_path)

    data, _files = uploader._prepare_upload_request(
        {
            "description": "description",
            "mediainfo": "mediainfo",
            "category_id": "2",
            "type_id": "3",
            "tmdb": "12345",
            "season_number": 2,
            "episode_number": 0,
            "season_pack": 1,
        },
        BytesIO(b"torrent"),
    )

    assert data["season_number"] == 2
    assert data["season_pack"] == 1
    assert "episode_number" not in data


def test_huno_multi_episode_upload_includes_end_episode(tmp_path: Path) -> None:
    uploader = _huno_uploader(tmp_path)

    data, _files = uploader._prepare_upload_request(
        {
            "description": "description",
            "mediainfo": "mediainfo",
            "category_id": "2",
            "type_id": "3",
            "tmdb": "12345",
            "season_number": 1,
            "episode_number": 27,
            "episode_number_end": 28,
        },
        BytesIO(b"torrent"),
    )

    assert data["episode_number"] == 27
    assert data["episode_number_end"] == 28


def test_standard_unit3d_request_keeps_description_and_mediainfo_as_fields(
    tmp_path: Path,
) -> None:
    uploader = AitherUploader(
        media_type=MediaType.MOVIE,
        api_key="api-key",
        torrent_file=tmp_path / "release.torrent",
        input_path=tmp_path / "Example.2026.1080p.WEB-DL-GRP.mkv",
        mediainfo_obj=MagicMock(),
    )
    torrent = BytesIO(b"torrent")
    payload = {"description": "description", "mediainfo": "mediainfo"}

    data, files = uploader._prepare_upload_request(payload, torrent)

    assert data is payload
    assert files == {"torrent": torrent}


@patch("src.backend.trackers.huno.niquests.get")
def test_huno_resolves_download_link_from_torrent_details(
    get: MagicMock, tmp_path: Path
) -> None:
    response = MagicMock()
    response.json.return_value = {
        "data": {
            "id": "42",
            "attributes": {
                "name": "Example (2026)",
                "download_link": "https://hawke.uno/torrent/download/42.key",
            },
        }
    }
    get.return_value.__enter__.return_value = response
    uploader = _huno_uploader(tmp_path)

    result = uploader._resolve_uploaded_torrent_download_url(
        {"torrent": {"id": "42", "attributes": {"name": "Example (2026)"}}}
    )

    assert result == "https://hawke.uno/torrent/download/42.key"
    get.assert_called_once_with(
        "https://hawke.uno/api/torrents/42",
        params={"api_token": "api-key"},
        headers=ANY,
        timeout=60,
    )
    response.raise_for_status.assert_called_once_with()


@patch("src.backend.trackers.huno.niquests.get")
def test_huno_uses_download_link_from_upload_response_without_details_request(
    get: MagicMock, tmp_path: Path
) -> None:
    uploader = _huno_uploader(tmp_path)

    result = uploader._resolve_uploaded_torrent_download_url(
        {
            "torrent": {
                "id": "42",
                "attributes": {
                    "download_link": "https://hawke.uno/torrent/download/42.key"
                },
            }
        }
    )

    assert result == "https://hawke.uno/torrent/download/42.key"
    get.assert_not_called()


def test_huno_resolves_relative_download_link_against_tracker(tmp_path: Path) -> None:
    uploader = _huno_uploader(tmp_path)

    result = uploader._resolve_uploaded_torrent_download_url(
        {
            "torrent": {
                "id": "42",
                "attributes": {"download_link": "/torrent/download/42.key"},
            }
        }
    )

    assert result == "https://hawke.uno/torrent/download/42.key"


@patch.object(HunoUploader, "_download_uploaded_torrent_with_retry")
@patch.object(
    HunoUploader,
    "_build_upload_payload",
    return_value={
        "name": "Ignored title",
        "description": "description",
        "mediainfo": "mediainfo",
        "category_id": "1",
        "type_id": "3",
        "tmdb": "12345",
    },
)
@patch("src.backend.trackers.unit3d_base.niquests.post")
def test_huno_upload_accepts_nested_success_response(
    post: MagicMock,
    _build_payload: MagicMock,
    download: MagicMock,
    tmp_path: Path,
) -> None:
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"torrent")
    response = MagicMock()
    response.json.return_value = {
        "success": True,
        "message": "Torrent uploaded successfully.",
        "data": {
            "torrent": {
                "id": "42",
                "attributes": {
                    "download_link": "https://hawke.uno/torrent/download/42.key"
                },
            },
            "moderation_status": "approved",
            "warnings": [],
            "name_issues": [],
        },
    }
    post.return_value.__enter__.return_value = response

    assert _huno_uploader(tmp_path).upload(tracker_title="Ignored title") is True

    request = post.call_args.kwargs
    assert request["headers"] == API_TRACKER_HEADERS
    assert request["data"] == {
        "category_id": "1",
        "type_id": "3",
        "tmdb": "12345",
    }
    assert request["files"]["description"] == (
        "description.txt",
        b"description",
        "text/plain",
    )
    assert request["files"]["mediainfo"] == (
        "mediainfo.txt",
        b"mediainfo",
        "text/plain",
    )
    download.assert_called_once_with("https://hawke.uno/torrent/download/42.key")
