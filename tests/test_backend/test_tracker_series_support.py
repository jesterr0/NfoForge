from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from pymediainfo import MediaInfo

from src.backend.trackers.aither import AitherUploader
from src.backend.trackers.beyondhd import BHDUploader
from src.backend.trackers.darkpeers import DarkPeersUploader
from src.backend.trackers.huno import HunoUploader
from src.backend.trackers.lst import LSTUploader
from src.backend.trackers.morethantv import MTVUploader
from src.backend.trackers.onlyencodes import OnlyEncodesUploader
from src.backend.trackers.reelflix import ReelFlixUploader
from src.backend.trackers.series_support import (
    UNSUPPORTED_SERIES_TRACKERS,
    supports_series_upload,
)
from src.backend.trackers.shareisland import ShareIslandUploader
from src.backend.trackers.torrentleech import TLUploader
from src.backend.trackers.unit3d_base import Unit3dBaseUploader
from src.backend.trackers.uploadcx import UploadCXUploader
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.aither import AitherType
from src.enums.trackers.beyondhd import (
    BHDCategoryID,
    BHDLiveRelease,
    BHDPromo,
    BHDSource,
    BHDType,
)
from src.enums.trackers.morethantv import MTVCategories
from src.enums.trackers.torrentleech import TLCategories
from src.exceptions import TrackerError


@pytest.mark.parametrize(
    ("tracker", "expected"),
    [
        (TrackerSelection.MORE_THAN_TV, True),
        (TrackerSelection.TORRENT_LEECH, True),
        (TrackerSelection.BEYOND_HD, True),
        (TrackerSelection.AITHER, True),
        (TrackerSelection.HUNO, True),
        (TrackerSelection.LST, True),
        (TrackerSelection.DARK_PEERS, True),
        (TrackerSelection.SHARE_ISLAND, True),
        (TrackerSelection.UPLOAD_CX, True),
        (TrackerSelection.ONLY_ENCODES, True),
        (TrackerSelection.PASS_THE_POPCORN, False),
        (TrackerSelection.REELFLIX, False),
    ],
)
def test_series_tracker_support_matrix(
    tracker: TrackerSelection, expected: bool
) -> None:
    assert supports_series_upload(tracker) is expected
    assert (tracker not in UNSUPPORTED_SERIES_TRACKERS) is expected


@pytest.mark.parametrize(
    ("title", "resolution", "is_pack", "expected"),
    [
        ("Example.Show.S01.1080p.WEB-DL", "1080p", True, TLCategories.TV_BOX_SETS),
        (
            "Example.Show.S01E01.1080p.WEB-DL",
            "1080p",
            False,
            TLCategories.TV_EPISODES_HD,
        ),
        (
            "Example.Show.S01E01.WEB-DL",
            "480p",
            False,
            TLCategories.TV_EPISODES,
        ),
    ],
)
def test_torrentleech_series_category_mapping(
    title: str, resolution: str, is_pack: bool, expected: TLCategories
) -> None:
    assert (
        TLUploader._detect_category(
            title=title,
            resolution=resolution,
            media_type=MediaType.SERIES,
            is_pack=is_pack,
        )
        == expected.value
    )


@pytest.mark.parametrize(
    ("release_title", "is_pack", "expected"),
    [
        ("Example.Show.S01.1080p.WEB-DL", True, MTVCategories.HD_SEASON),
        ("Example.Show.S01.480p.WEB-DL", True, MTVCategories.SD_SEASON),
        ("Example.Show.S01E01.1080p.WEB-DL", False, MTVCategories.HD_EPISODE),
        ("Example.Show.2024.02.03.480p.WEB-DL", False, MTVCategories.SD_EPISODE),
    ],
)
def test_morethantv_series_category_mapping(
    release_title: str, is_pack: bool, expected: MTVCategories
) -> None:
    assert MTVUploader._get_cat_id(
        release_title=release_title,
        media_type=MediaType.SERIES,
        is_pack=is_pack,
    ) == str(expected.value)


@pytest.mark.parametrize(
    ("resolution", "is_pack", "expected_tags"),
    [
        ("1080p", True, {"hd.season"}),
        ("480p", True, {"sd.season"}),
        ("1080p", False, {"episode.release", "hd.episode"}),
        ("480p", False, {"episode.release", "sd.episode"}),
    ],
)
def test_morethantv_series_tags(
    resolution: str, is_pack: bool, expected_tags: set[str]
) -> None:
    assert MTVUploader.find_series_tags(resolution, is_pack) == expected_tags


def test_beyondhd_series_type_source_category_and_pack_payload(tmp_path: Path) -> None:
    uploader = BHDUploader(
        api_key="api-key",
        torrent_file=tmp_path / "upload.torrent",
        input_path=tmp_path / "Example.Show.S00E01.1080p.WEB-DL.x264.mkv",
        media_type=MediaType.SERIES,
    )

    payload = uploader._build_upload_payload(
        tracker_title=None,
        imdb_id="tt1234567",
        tmdb_id="12345",
        nfo="description",
        is_pack=True,
        is_special=True,
        internal=True,
        live_release=BHDLiveRelease.DRAFT,
        anonymous=True,
        promo=BHDPromo.FREELEECH,
        stream_optimized=True,
    )

    assert payload["category_id"] == BHDCategoryID.TV.value
    assert payload["source"] == BHDSource.WEB.value
    assert payload["type"] == BHDType.P_1080P.value
    assert payload["pack"] == 1
    assert payload["special"] == 1
    assert payload["imdb_id"] == "tt1234567"
    assert payload["tmdb_id"] == "12345"
    assert payload["description"] == "description"
    assert payload["nfo"] == "description"
    assert payload["internal"] == 1
    assert payload["live"] == BHDLiveRelease.DRAFT.value
    assert payload["anon"] == 1
    assert payload["promo"] == BHDPromo.FREELEECH.value
    assert payload["stream"] == 1


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Example.Show.S01E01.1080p.WEB-DL.H.264.mkv", AitherType.WEBDL),
        ("Example.Show.S01E01.1080p.WEBDL.H.264.mkv", AitherType.WEBDL),
        ("Example.Show.S01E01.1080p.WEBRip.H.264.mkv", AitherType.WEBRIP),
        ("Example.Show.S01E01.1080p.HDTV.H.264.mkv", AitherType.HDTV),
        # bare "WEB" (no -DL/-Rip suffix) is a common scene/P2P tag and must
        # not fall through to the ENCODE branch just because it also carries
        # a codec tag (h264/x264/etc.)
        ("Show.S01E01.1080p.WEB.H264.mkv", AitherType.WEBDL),
    ],
)
def test_unit3d_series_type_detection_prefers_release_source(
    tmp_path: Path, filename: str, expected: AitherType
) -> None:
    uploader = AitherUploader(
        media_type=MediaType.SERIES,
        api_key="api-key",
        torrent_file=tmp_path / "upload.torrent",
        input_path=tmp_path / filename,
        mediainfo_obj=cast(MediaInfo, object()),
    )

    assert uploader._get_type_id() == expected.value


def test_unit3d_series_web_in_title_only_resolves_encode(
    tmp_path: Path,
) -> None:
    """A show title that merely contains the word "web" (e.g. "Spider.Web")
    must not be misread as a bare-"WEB" source tag. With no resolution- or
    codec-adjacent "web" release-tag, this is a plain codec encode and must
    resolve to ENCODE, not WEBDL."""
    uploader = AitherUploader(
        media_type=MediaType.SERIES,
        api_key="api-key",
        torrent_file=tmp_path / "upload.torrent",
        input_path=tmp_path / "Spider.Web.S01E01.1080p.x264-GRP.mkv",
        mediainfo_obj=cast(MediaInfo, object()),
    )

    assert uploader._get_type_id() == AitherType.ENCODE.value


def test_unit3d_movie_encode_without_web_marker_still_resolves_encode(
    tmp_path: Path,
) -> None:
    """A genuine encode with no web/hdtv/disc marker must still resolve to
    ENCODE; the bare-"WEB" fallback must not over-match unrelated titles."""
    uploader = AitherUploader(
        media_type=MediaType.MOVIE,
        api_key="api-key",
        torrent_file=tmp_path / "upload.torrent",
        input_path=tmp_path / "Movie.2020.1080p.x264.mkv",
        mediainfo_obj=cast(MediaInfo, object()),
    )

    assert uploader._get_type_id() == AitherType.ENCODE.value


@pytest.mark.parametrize(
    "uploader_cls",
    [
        AitherUploader,
        HunoUploader,
        LSTUploader,
        DarkPeersUploader,
        ShareIslandUploader,
        UploadCXUploader,
        OnlyEncodesUploader,
    ],
)
def test_supported_unit3d_trackers_resolve_series_tv_category(
    tmp_path: Path, uploader_cls: Callable[..., Unit3dBaseUploader]
) -> None:
    uploader = uploader_cls(
        media_type=MediaType.SERIES,
        api_key="api-key",
        torrent_file=tmp_path / "upload.torrent",
        input_path=tmp_path / "Example.Show.S01E01.1080p.WEB-DL.H.264.mkv",
        mediainfo_obj=cast(MediaInfo, object()),
    )

    assert uploader._get_category_id() == "2"


def test_unit3d_single_episode_payload_includes_episode_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(AitherUploader, "_get_resolution_id", lambda self: "1080p")
    monkeypatch.setattr(AitherUploader, "_standard_definition", lambda self: False)
    input_path = tmp_path / "Example.Show.S01E01.1080p.WEB-DL.H.264.mkv"
    input_path.write_bytes(b"placeholder")
    uploader = AitherUploader(
        media_type=MediaType.SERIES,
        api_key="api-key",
        torrent_file=tmp_path / "upload.torrent",
        input_path=input_path,
        mediainfo_obj=cast(MediaInfo, object()),
    )

    payload = uploader._build_upload_payload(
        tracker_title=None,
        season_number=1,
        episode_number=1,
        season_pack=False,
    )

    assert payload["season_number"] == 1
    assert payload["episode_number"] == 1
    assert "season_pack" not in payload


def test_unit3d_season_pack_payload_includes_season_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(AitherUploader, "_get_resolution_id", lambda self: "1080p")
    monkeypatch.setattr(AitherUploader, "_standard_definition", lambda self: False)
    input_path = tmp_path / "Example.Show.S01.1080p.WEB-DL.H.264.mkv"
    input_path.write_bytes(b"placeholder")
    uploader = AitherUploader(
        media_type=MediaType.SERIES,
        api_key="api-key",
        torrent_file=tmp_path / "upload.torrent",
        input_path=input_path,
        mediainfo_obj=cast(MediaInfo, object()),
    )

    payload = uploader._build_upload_payload(
        tracker_title=None,
        season_number=1,
        episode_number=None,
        season_pack=True,
    )

    assert payload["season_number"] == 1
    assert payload["season_pack"] == 1
    assert "episode_number" not in payload


def test_unit3d_movie_payload_excludes_series_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(AitherUploader, "_get_resolution_id", lambda self: "1080p")
    monkeypatch.setattr(AitherUploader, "_standard_definition", lambda self: False)
    input_path = tmp_path / "Example.Movie.2024.1080p.WEB-DL.H.264.mkv"
    input_path.write_bytes(b"placeholder")
    uploader = AitherUploader(
        media_type=MediaType.MOVIE,
        api_key="api-key",
        torrent_file=tmp_path / "upload.torrent",
        input_path=input_path,
        mediainfo_obj=cast(MediaInfo, object()),
    )

    payload = uploader._build_upload_payload(
        tracker_title=None,
        season_number=1,
        episode_number=1,
        season_pack=True,
    )

    assert "season_number" not in payload
    assert "episode_number" not in payload
    assert "season_pack" not in payload


def test_reelflix_does_not_resolve_series_tv_category(tmp_path: Path) -> None:
    uploader = ReelFlixUploader(
        media_type=MediaType.SERIES,
        api_key="api-key",
        torrent_file=tmp_path / "upload.torrent",
        input_path=tmp_path / "Example.Show.S01E01.1080p.WEB-DL.H.264.mkv",
        mediainfo_obj=cast(MediaInfo, object()),
    )

    with pytest.raises(TrackerError, match="does not support"):
        uploader._get_category_id()
