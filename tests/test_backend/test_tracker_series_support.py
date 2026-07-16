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
        ("Example.Show.S01.2160p.WEB-DL", True, MTVCategories.HD_SEASON),
        ("Example.Show.S01E01.2160p.WEB-DL", False, MTVCategories.HD_EPISODE),
        # 8K releases must resolve to the HD category, matching the HD tag
        # produced by find_series_tags for the same resolution.
        ("Example.Show.S01.4320p.WEB-DL", True, MTVCategories.HD_SEASON),
        ("Example.Show.S01E01.4320p.WEB-DL", False, MTVCategories.HD_EPISODE),
        # MTV only distinguishes SD vs HD, so everything above SD -- including
        # 1440p/1440i (QHD) and interlaced 2160i/1080i -- resolves to the HD
        # category. Locks in the intended behavior of the shared _is_hd
        # predicate (see morethantv.py _RESOLUTION_TOKEN): any resolution of
        # 720 lines or more, interlaced or progressive, is HD.
        ("Example.Show.S01.1440p.WEB-DL", True, MTVCategories.HD_SEASON),
        ("Example.Show.S01E01.1440p.WEB-DL", False, MTVCategories.HD_EPISODE),
        ("Example.Show.S01.1440i.WEB-DL", True, MTVCategories.HD_SEASON),
        ("Example.Show.S01E01.1440i.WEB-DL", False, MTVCategories.HD_EPISODE),
        ("Example.Show.S01.2160i.WEB-DL", True, MTVCategories.HD_SEASON),
        ("Example.Show.S01E01.2160i.WEB-DL", False, MTVCategories.HD_EPISODE),
        ("Example.Show.S01.1080i.WEB-DL", True, MTVCategories.HD_SEASON),
        ("Example.Show.S01E01.1080i.WEB-DL", False, MTVCategories.HD_EPISODE),
        # 720i is the interlaced counterpart of 720p and must also be HD --
        # this was previously missed because the old pattern only matched a
        # literal "720p" token, not "720i".
        ("Example.Show.S01.720i.WEB-DL", True, MTVCategories.HD_SEASON),
        ("Example.Show.S01E01.720i.WEB-DL", False, MTVCategories.HD_EPISODE),
        # SD boundary: below 720 lines (576p), and no resolution token at
        # all, must both remain SD.
        ("Example.Show.S01.576p.WEB-DL", True, MTVCategories.SD_SEASON),
        ("Example.Show.S01E01.576p.WEB-DL", False, MTVCategories.SD_EPISODE),
        ("Example.Show.S01E01.WEB-DL", False, MTVCategories.SD_EPISODE),
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
        ("2160p", True, {"hd.season"}),
        ("2160p", False, {"episode.release", "hd.episode"}),
        ("4320p", True, {"hd.season"}),
        ("4320p", False, {"episode.release", "hd.episode"}),
        # 1440p/1440i (QHD) and interlaced 2160i/1080i are HD for MTV, same
        # as their progressive counterparts -- MTV only distinguishes SD vs
        # HD, and everything above SD is HD.
        ("1440p", True, {"hd.season"}),
        ("1440p", False, {"episode.release", "hd.episode"}),
        ("1440i", True, {"hd.season"}),
        ("1440i", False, {"episode.release", "hd.episode"}),
        ("2160i", True, {"hd.season"}),
        ("2160i", False, {"episode.release", "hd.episode"}),
        ("1080i", True, {"hd.season"}),
        ("1080i", False, {"episode.release", "hd.episode"}),
        # 720i (interlaced) must tag the same as 720p.
        ("720i", True, {"hd.season"}),
        ("720i", False, {"episode.release", "hd.episode"}),
        # SD boundary: below 720 lines remains SD.
        ("576p", True, {"sd.season"}),
        ("576p", False, {"episode.release", "sd.episode"}),
    ],
)
def test_morethantv_series_tags(
    resolution: str, is_pack: bool, expected_tags: set[str]
) -> None:
    assert MTVUploader.find_series_tags(resolution, is_pack) == expected_tags


@pytest.mark.parametrize(
    ("resolution", "is_pack"),
    [
        ("720p", True),
        ("720i", True),
        ("1080p", True),
        ("1080i", True),
        ("1440p", True),
        ("1440i", True),
        ("2160p", True),
        ("2160i", True),
        ("4320p", True),
        ("480p", True),
        ("576p", True),
        ("720p", False),
        ("720i", False),
        ("1080p", False),
        ("1080i", False),
        ("1440p", False),
        ("1440i", False),
        ("2160p", False),
        ("2160i", False),
        ("4320p", False),
        ("480p", False),
        ("576p", False),
    ],
)
def test_morethantv_series_category_and_tag_agree_on_hd(
    resolution: str, is_pack: bool
) -> None:
    """The season/episode category and the season/episode tag must always
    agree on whether a release is HD or SD. An 8K (4320p) release must not
    be tagged HD while its category is categorized as SD (or vice versa),
    and genuinely-SD releases must remain SD in both places. This also locks
    in that everything above SD -- including 720i, 1440p/1440i (QHD), and
    interlaced 2160i/1080i -- is HD in both places, per MTV's SD-vs-HD-only
    distinction."""
    release_title = (
        f"Example.Show.S01.{resolution}.WEB-DL"
        if is_pack
        else f"Example.Show.S01E01.{resolution}.WEB-DL"
    )
    category = MTVUploader._get_cat_id(
        release_title=release_title,
        media_type=MediaType.SERIES,
        is_pack=is_pack,
    )
    tags = MTVUploader.find_series_tags(resolution, is_pack)

    category_is_hd = category in (
        str(MTVCategories.HD_SEASON.value),
        str(MTVCategories.HD_EPISODE.value),
    )
    tag_is_hd = "hd.season" in tags or "hd.episode" in tags

    assert category_is_hd == tag_is_hd


def test_morethantv_series_720i_episode_end_to_end() -> None:
    """End-to-end: a 720i episode must resolve to the HD_EPISODE category
    and be tagged hd.episode, matching the >=720-line HD threshold."""
    release_title = "Example.Show.S01E01.720i.WEB-DL"
    category = MTVUploader._get_cat_id(
        release_title=release_title,
        media_type=MediaType.SERIES,
        is_pack=False,
    )
    tags = MTVUploader.find_series_tags("720i", is_pack=False)

    assert category == str(MTVCategories.HD_EPISODE.value)
    assert "hd.episode" in tags


@pytest.mark.parametrize(
    ("release_title", "expected"),
    [
        ("Example.Movie.2024.720p.WEB-DL", MTVCategories.HD_MOVIES),
        ("Example.Movie.2024.720i.WEB-DL", MTVCategories.HD_MOVIES),
        ("Example.Movie.2024.1080p.WEB-DL", MTVCategories.HD_MOVIES),
        ("Example.Movie.2024.1080i.WEB-DL", MTVCategories.HD_MOVIES),
        ("Example.Movie.2024.1440p.WEB-DL", MTVCategories.HD_MOVIES),
        ("Example.Movie.2024.1440i.WEB-DL", MTVCategories.HD_MOVIES),
        ("Example.Movie.2024.2160p.WEB-DL", MTVCategories.HD_MOVIES),
        ("Example.Movie.2024.2160i.WEB-DL", MTVCategories.HD_MOVIES),
        ("Example.Movie.2024.4320p.WEB-DL", MTVCategories.HD_MOVIES),
        ("Example.Movie.2024.480p.WEB-DL", MTVCategories.SD_MOVIES),
        ("Example.Movie.2024.576p.WEB-DL", MTVCategories.SD_MOVIES),
        ("Example.Movie.2024.WEB-DL", MTVCategories.SD_MOVIES),
    ],
)
def test_morethantv_movie_category_mapping(
    release_title: str, expected: MTVCategories
) -> None:
    assert MTVUploader._get_cat_id(
        release_title=release_title,
        media_type=MediaType.MOVIE,
        is_pack=False,
    ) == str(expected.value)


@pytest.mark.parametrize(
    ("resolution", "expected_tags"),
    [
        ("720p", {"hd.movie"}),
        ("720i", {"hd.movie"}),
        ("1080p", {"hd.movie"}),
        ("1080i", {"hd.movie"}),
        ("1440p", {"hd.movie"}),
        ("1440i", {"hd.movie"}),
        ("2160p", {"hd.movie"}),
        ("2160i", {"hd.movie"}),
        ("4320p", {"hd.movie"}),
        ("480p", set()),
        ("576p", set()),
    ],
)
def test_morethantv_movie_tags(resolution: str, expected_tags: set[str]) -> None:
    assert MTVUploader.find_movies_tags(resolution) == expected_tags


@pytest.mark.parametrize(
    "resolution",
    [
        "720p",
        "720i",
        "1080p",
        "1080i",
        "1440p",
        "1440i",
        "2160p",
        "2160i",
        "4320p",
        "480p",
        "576p",
    ],
)
def test_morethantv_movie_category_and_tag_agree_on_hd(resolution: str) -> None:
    """The movie category and the movie tag must always agree on whether a
    release is HD or SD, mirroring the series-side guarantee above."""
    release_title = f"Example.Movie.2024.{resolution}.WEB-DL"
    category = MTVUploader._get_cat_id(
        release_title=release_title,
        media_type=MediaType.MOVIE,
        is_pack=False,
    )
    tags = MTVUploader.find_movies_tags(resolution)

    category_is_hd = category == str(MTVCategories.HD_MOVIES.value)
    tag_is_hd = "hd.movie" in tags

    assert category_is_hd == tag_is_hd


def test_morethantv_movie_4320p_end_to_end() -> None:
    """End-to-end: a 4320p (8K) movie must resolve to the HD_MOVIES category
    and be tagged hd.movie, matching the >=720-line HD threshold."""
    release_title = "Example.Movie.2024.4320p.WEB-DL"
    category = MTVUploader._get_cat_id(
        release_title=release_title,
        media_type=MediaType.MOVIE,
        is_pack=False,
    )
    tags = MTVUploader.find_movies_tags("4320p")

    assert category == str(MTVCategories.HD_MOVIES.value)
    assert "hd.movie" in tags


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
