from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

from pymediainfo import MediaInfo
import pytest

from src.backend.trackers.hdb import (
    HDBSearch,
    HDBUploader,
    hdb_category_id,
    hdb_codec_id,
    hdb_medium_id,
)
from src.enums.media_type import MediaType
from src.enums.trackers.hdb import HDBCategory, HDBCodec, HDBMedium
from src.exceptions import TrackerError


def _mediainfo(video_format: str | None) -> MediaInfo:
    return cast(
        MediaInfo,
        SimpleNamespace(video_tracks=[SimpleNamespace(format=video_format)]),
    )


def _uploader(
    torrent_file: Path, media_type: MediaType = MediaType.MOVIE
) -> HDBUploader:
    return HDBUploader(
        username="user",
        passkey="passkey",
        session_cookie="PHPSESSID=abc; uid=123",
        torrent_file=torrent_file,
        input_path=torrent_file.parent / "Example.2026.1080p.BluRay.REMUX.AVC-GRP.mkv",
        media_type=media_type,
        mediainfo_obj=_mediainfo("AVC"),
    )


# ---------------------------------------------------------------------------
# category/codec/medium ID mapping -- the three fields HDBits actually
# validates before accepting an upload or search (per upbrr's validation.go).
# ---------------------------------------------------------------------------


def test_hdb_category_id_maps_movie_and_series() -> None:
    assert hdb_category_id(MediaType.MOVIE) == HDBCategory.MOVIE.value
    assert hdb_category_id(MediaType.SERIES) == HDBCategory.TV.value


def test_hdb_category_id_documentary_genre_overrides_media_type() -> None:
    assert (
        hdb_category_id(MediaType.MOVIE, genre_names=("Action", "Documentary"))
        == HDBCategory.DOCUMENTARY.value
    )
    # case-insensitive
    assert (
        hdb_category_id(MediaType.SERIES, genre_names=("documentary",))
        == HDBCategory.DOCUMENTARY.value
    )


@pytest.mark.parametrize(
    ("video_format", "expected"),
    [
        ("AVC", HDBCodec.AVC),
        ("HEVC", HDBCodec.HEVC),
        ("VC-1", HDBCodec.VC1),
        ("VP9", HDBCodec.VP9),
        ("MPEG Video", HDBCodec.MPEG2),
        ("MPEG-4 Visual", HDBCodec.XVID),
    ],
)
def test_hdb_codec_id_maps_known_formats(video_format: str, expected: HDBCodec) -> None:
    assert hdb_codec_id(_mediainfo(video_format)) == expected.value


def test_hdb_codec_id_raises_for_unknown_format() -> None:
    with pytest.raises(TrackerError, match="Codec ID"):
        hdb_codec_id(_mediainfo("Theora"))


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Example.2026.1080p.BluRay.REMUX.AVC-GRP.mkv", HDBMedium.REMUX),
        ("Example.2026.1080p.BluRay.AVC-GRP.mkv", HDBMedium.BLURAY),
        ("Example.2026.1080p.WEB-DL.DDP5.1.H.264-GRP.mkv", HDBMedium.WEBDL),
        ("Example.2026.1080p.WEBRip.DDP5.1.H.264-GRP.mkv", HDBMedium.ENCODE),
        ("Example.S01E01.1080p.HDTV.H264-GRP.mkv", HDBMedium.CAPTURE),
        ("Example.2026.1080p.H264-GRP.mkv", HDBMedium.ENCODE),
    ],
)
def test_hdb_medium_id_maps_source_types(filename: str, expected: HDBMedium) -> None:
    assert hdb_medium_id(Path(filename)) == expected.value


def test_hdb_medium_id_raises_when_unmappable() -> None:
    with pytest.raises(TrackerError, match="Medium ID"):
        hdb_medium_id(Path("Example.2026.mkv"))


# ---------------------------------------------------------------------------
# generate_release_title
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected_substring"),
    [
        ("Example.2026.1080p.H.265-GRP", "HEVC"),
        ("Example.2026.1080p.DV.HDR-GRP", "DoVi"),
        ("Example.2026.1080p.HDR.HEVC-GRP", "HDR10"),
        ("Example.2026.1080p.HDR10+.HEVC-GRP", "HDR10+"),
        ("Example.2026.1080p.BluRay.REMUX-GRP", "Remux"),
        # the audio channel layout must survive the period stripping
        ("Example.2026.1080p.BluRay.DTS-HD.MA.5.1.x264-GRP", "DTS-HD MA 5.1"),
        ("Example.2026.1080p.WEB-DL.AAC.2.0.H.264-GRP", "AAC 2.0"),
    ],
)
def test_generate_release_title_substitutions(
    title: str, expected_substring: str
) -> None:
    assert expected_substring in HDBUploader.generate_release_title(title)


def test_generate_release_title_does_not_downgrade_hdr10_plus() -> None:
    result = HDBUploader.generate_release_title("Example.2026.1080p.HDR10+.HEVC-GRP")
    assert "HDR10+" in result
    # must not have been further rewritten into "HDR1010+" by the plain
    # HDR->HDR10 substitution running a second time on top of "HDR10+"
    assert "HDR1010" not in result


# ---------------------------------------------------------------------------
# session cookie parsing
# ---------------------------------------------------------------------------


def test_load_session_cookie_parses_name_value_pairs(tmp_path: Path) -> None:
    uploader = _uploader(tmp_path / "release.torrent")
    cookie_names = {cookie.name for cookie in uploader._session.cookies}
    assert cookie_names == {"PHPSESSID", "uid"}


def test_load_session_cookie_ignores_malformed_segments(tmp_path: Path) -> None:
    torrent_file = tmp_path / "release.torrent"
    uploader = HDBUploader(
        username="user",
        passkey="passkey",
        session_cookie="  ; PHPSESSID=abc ; garbage ; =novalue ;",
        torrent_file=torrent_file,
        input_path=torrent_file.parent / "Example.mkv",
        media_type=MediaType.MOVIE,
        mediainfo_obj=_mediainfo("AVC"),
    )
    cookie_names = {cookie.name for cookie in uploader._session.cookies}
    assert cookie_names == {"PHPSESSID"}


# ---------------------------------------------------------------------------
# upload() external-id requirement (upbrr's MetadataPolicy)
# ---------------------------------------------------------------------------


def test_upload_requires_imdb_for_movies(tmp_path: Path) -> None:
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"d8:announce1:ae")
    uploader = _uploader(torrent_file, media_type=MediaType.MOVIE)

    with pytest.raises(TrackerError, match="IMDb id for movie"):
        uploader.upload(tracker_title="Example", nfo="")


def test_upload_requires_imdb_or_tvdb_for_series(tmp_path: Path) -> None:
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"d8:announce1:ae")
    uploader = _uploader(torrent_file, media_type=MediaType.SERIES)

    with pytest.raises(TrackerError, match="IMDb or TVDB id"):
        uploader.upload(tracker_title="Example", nfo="")


# ---------------------------------------------------------------------------
# validate_cookies
# ---------------------------------------------------------------------------


def test_validate_cookies_detects_logged_in_session(tmp_path: Path) -> None:
    torrent_file = tmp_path / "release.torrent"
    uploader = _uploader(torrent_file)
    response = MagicMock()
    response.text = '<html><a href="/logout.php">Logout</a></html>'
    with patch.object(uploader._session, "get", return_value=response):
        assert uploader.validate_cookies() is True


def test_validate_cookies_detects_expired_session(tmp_path: Path) -> None:
    torrent_file = tmp_path / "release.torrent"
    uploader = _uploader(torrent_file)
    response = MagicMock()
    response.text = "<html>Please log in</html>"
    with patch.object(uploader._session, "get", return_value=response):
        assert uploader.validate_cookies() is False


# ---------------------------------------------------------------------------
# _download_new_torrent
# ---------------------------------------------------------------------------


@patch("niquests.Session.get")
@patch("niquests.Session.post")
def test_download_new_torrent_writes_file_atomically(
    post: MagicMock, get: MagicMock, tmp_path: Path
) -> None:
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"placeholder")
    uploader = _uploader(torrent_file)

    info_response = MagicMock()
    info_response.json.return_value = {"data": [{"filename": "Example.torrent"}]}
    post.return_value = info_response

    download_response = MagicMock()
    download_response.headers = {"Content-Type": "application/x-bittorrent"}
    download_response.iter_content.return_value = [b"d8:announce1:ae"]
    get.return_value.__enter__.return_value = download_response

    result = uploader._download_new_torrent("123")

    assert result == torrent_file
    assert torrent_file.read_bytes() == b"d8:announce1:ae"
    assert not list(tmp_path.glob("*.part"))


@patch("niquests.Session.get")
@patch("niquests.Session.post")
def test_download_new_torrent_rejects_invalid_content(
    post: MagicMock, get: MagicMock, tmp_path: Path
) -> None:
    torrent_file = tmp_path / "release.torrent"
    torrent_file.write_bytes(b"placeholder")
    uploader = _uploader(torrent_file)

    info_response = MagicMock()
    info_response.json.return_value = {"data": [{"filename": "Example.torrent"}]}
    post.return_value = info_response

    download_response = MagicMock()
    download_response.headers = {"Content-Type": "text/html"}
    download_response.iter_content.return_value = [b"<html>Access denied</html>"]
    get.return_value.__enter__.return_value = download_response

    with pytest.raises(TrackerError, match="not a valid torrent"):
        uploader._download_new_torrent("123")

    assert torrent_file.read_bytes() == b"placeholder"
    assert not list(tmp_path.glob("*.part"))


# ---------------------------------------------------------------------------
# HDBSearch -- best-effort ID derivation
# ---------------------------------------------------------------------------


@patch("niquests.Session.post")
def test_search_omits_unmappable_ids_instead_of_aborting(post: MagicMock) -> None:
    response = MagicMock()
    response.json.return_value = {"data": []}
    post.return_value = response

    search = HDBSearch(username="user", passkey="passkey")
    search.search(
        input_path=Path("Example.2026.mkv"),
        media_type=MediaType.MOVIE,
        mediainfo_obj=None,
    )

    sent_payload = cast(dict[str, Any], post.call_args.kwargs["json"])
    assert "medium" not in sent_payload
    assert "codec" not in sent_payload
    assert sent_payload["category"] == HDBCategory.MOVIE.value
    assert sent_payload["search"] == "Example.2026"
