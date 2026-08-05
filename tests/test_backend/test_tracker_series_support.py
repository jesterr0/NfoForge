import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

from pymediainfo import MediaInfo
import pytest

from src.backend.process import ProcessBackEnd
from src.backend.trackers.aither import AitherUploader
from src.backend.trackers.beyondhd import BHDUploader
from src.backend.trackers.darkpeers import DarkPeersUploader
from src.backend.trackers.huno import HunoUploader
from src.backend.trackers.lst import LSTUploader
from src.backend.trackers.media_support import (
    TRACKER_SUPPORTED_MEDIA,
    UNSUPPORTED_MOVIE_TRACKERS,
    UNSUPPORTED_SERIES_TRACKERS,
    supports_media,
    supports_series_upload,
)
from src.backend.trackers.morethantv import MTVUploader
from src.backend.trackers.onlyencodes import OnlyEncodesUploader
from src.backend.trackers.reelflix import ReelFlixUploader
from src.backend.trackers.shareisland import ShareIslandUploader
from src.backend.trackers.torrentleech import TLUploader
from src.backend.trackers.unit3d_base import Unit3dBaseUploader
from src.backend.trackers.uploadcx import UploadCXUploader
from src.backend.utils.anime import is_anime_release
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.enums.series import EpisodeFormat
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
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.payloads.series import SeriesReleaseInfo, build_series_release_info


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
        (TrackerSelection.HDB, True),
        (TrackerSelection.PASS_THE_POPCORN, False),
        (TrackerSelection.REELFLIX, False),
    ],
)
def test_series_tracker_support_matrix(
    tracker: TrackerSelection, expected: bool
) -> None:
    assert supports_series_upload(tracker) is expected
    assert (tracker not in UNSUPPORTED_SERIES_TRACKERS) is expected


def test_every_tracker_has_a_supported_media_row() -> None:
    """TRACKER_SUPPORTED_MEDIA is the single source of truth for media support;
    a newly added TrackerSelection must not be silently omitted from it."""
    missing = set(TrackerSelection) - set(TRACKER_SUPPORTED_MEDIA)
    assert not missing, f"trackers missing a media-support row: {missing}"
    # every row must declare at least one supported media type
    for tracker, media in TRACKER_SUPPORTED_MEDIA.items():
        assert media, tracker


@pytest.mark.parametrize("tracker", list(TrackerSelection))
def test_all_trackers_support_movie_uploads(tracker: TrackerSelection) -> None:
    """Every tracker supports movie uploads today, so the derived movie
    exclusion set is empty."""
    assert supports_media(tracker, MediaType.MOVIE) is True


def test_derived_sets_match_supported_media_rows() -> None:
    """The derived exclusion sets must always agree with the source table."""
    assert UNSUPPORTED_SERIES_TRACKERS == frozenset(
        t for t, m in TRACKER_SUPPORTED_MEDIA.items() if MediaType.SERIES not in m
    )
    assert UNSUPPORTED_MOVIE_TRACKERS == frozenset(
        t for t, m in TRACKER_SUPPORTED_MEDIA.items() if MediaType.MOVIE not in m
    )
    assert UNSUPPORTED_MOVIE_TRACKERS == frozenset()


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
    ("title", "resolution", "media_type", "is_pack"),
    [
        ("Example.Film.2026.2160p.BluRay", "2160p", MediaType.MOVIE, False),
        ("Example.Show.S01.1080p.WEB-DL", "1080p", MediaType.SERIES, True),
        ("Example.Show.S01E01.1080p.WEB-DL", "1080p", MediaType.SERIES, False),
    ],
)
def test_torrentleech_anime_category_overrides_standard_categories(
    title: str, resolution: str, media_type: MediaType, is_pack: bool
) -> None:
    assert (
        TLUploader._detect_category(
            title=title,
            resolution=resolution,
            media_type=media_type,
            is_pack=is_pack,
            is_anime=True,
        )
        == TLCategories.ANIME.value
    )


@pytest.mark.parametrize(
    ("anilist_id", "anilist_data", "episode_format", "expected"),
    [
        ("123", None, EpisodeFormat.STANDARD, True),
        (None, {"id": "123"}, EpisodeFormat.STANDARD, True),
        (None, None, EpisodeFormat.ANIME_ABSOLUTE, True),
        (None, None, EpisodeFormat.STANDARD, False),
    ],
)
def test_torrentleech_anime_signal_uses_metadata_or_series_format(
    anilist_id: str | None,
    anilist_data: dict[str, str] | None,
    episode_format: EpisodeFormat,
    expected: bool,
) -> None:
    media_input = MediaInputPayload(series_episode_format=episode_format)
    media_search = MediaSearchPayload(
        anilist_id=anilist_id,
        anilist_data=anilist_data,
    )

    assert is_anime_release(media_input, media_search) is expected


@patch("src.backend.process.tl_upload", return_value=True)
def test_torrentleech_upload_receives_derived_anime_signal(
    tl_upload: MagicMock,
) -> None:
    process = object.__new__(ProcessBackEnd)
    process.config = MagicMock()
    process.config.settings.trackers.torrent_leech.torrent_passkey = "announce-key"
    process.config.settings.general.timeout = 60

    context = MagicMock()
    context.media_input.require_first_file.return_value = Path("episode.mkv")
    context.media_input.require_mediainfo.return_value = MagicMock()
    context.media_input.require_media_type.return_value = MediaType.SERIES
    context.media_input.series_episode_format = EpisodeFormat.STANDARD
    context.media_search = MediaSearchPayload(anilist_id="123")
    release_info = MagicMock(is_pack=False)

    assert (
        process.upload(
            tracker=TrackerSelection.TORRENT_LEECH,
            torrent_file=Path("release.torrent"),
            nfo="",
            tracker_title="Example Show",
            context=context,
            release_info=release_info,
        )
        is True
    )
    assert tl_upload.call_args.kwargs["is_anime"] is True


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

    # process.py now always sends a real episode_number (release_info's
    # episode_start) alongside season_pack, relying on the builder's guard
    # (not season_pack and episode_number is not None) to drop it -- this
    # proves that guard holds even when episode_number is populated, not
    # just when it's None.
    payload = uploader._build_upload_payload(
        tracker_title=None,
        season_number=1,
        episode_number=1,
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


# ---------------------------------------------------------------------------
# Guard-site coverage: the table above (UNSUPPORTED_SERIES_TRACKERS) is fully
# tested, but nothing exercised the two call sites that actually *consume*
# it -- ProcessBackEnd.upload (process.py:1607) and ProcessBackEnd.dupe_checks
# (process.py:153). Without the former, a series upload to an unsupporting
# tracker would be attempted for real.
# ---------------------------------------------------------------------------


@dataclass
class _UploadFixture:
    """Everything `ProcessBackEnd.upload`/`dupe_checks` need beyond the
    tracker itself."""

    torrent_file: Path
    context: ProcessingContext
    release_info: SeriesReleaseInfo


def _mediainfo_obj() -> MediaInfo:
    return MediaInfo(
        """<Mediainfo><File>
        <track type="General"><Duration>60000</Duration><File_size>1000</File_size></track>
        <track type="Video"><Width>1920</Width><Height>1080</Height><Scan_type>Progressive</Scan_type><Frame_rate>24.000</Frame_rate><Format>AVC</Format></track>
        <track type="Audio"><Format>AC-3</Format><Channel_s>2</Channel_s><Language>en</Language></track>
        </File></Mediainfo>"""
    )


def _process_backend() -> ProcessBackEnd:
    """Build a `ProcessBackEnd` via `object.__new__`, skipping `__init__`
    (template loading, torrent-client bookkeeping) that these guard tests
    have no use for -- the same shortcut already used by
    `test_torrentleech_upload_receives_derived_anime_signal` above and by
    `test_flat_filter_runtime.py`. `config` is a MagicMock; the handful of
    credential fields that `upload`/`dupe_checks` can reach once the series
    guard is cleared are pinned to falsy values so a supported tracker fails
    on "missing credentials" rather than attempting a real network call.
    """
    backend = object.__new__(ProcessBackEnd)
    backend.config = MagicMock()
    backend.config.settings.trackers.more_than_tv.username = ""
    backend.config.settings.trackers.more_than_tv.password = ""
    backend.config.settings.trackers.pass_the_popcorn.api_user = ""
    backend.config.settings.trackers.reelflix.api_key = ""
    return backend


@pytest.fixture
def series_context() -> _UploadFixture:
    file_path = Path("Show.S01E01.1080p.WEB-DL.H.264-GRP.mkv")
    media_input = MediaInputPayload(
        input_path=Path("Show.S01"),
        media_type=MediaType.SERIES,
        file_list=[file_path],
        file_list_mediainfo={file_path: _mediainfo_obj()},
    )
    context = ProcessingContext(
        media_input=media_input,
        media_search=MediaSearchPayload(media_type=MediaType.SERIES),
    )
    return _UploadFixture(
        torrent_file=Path("release.torrent"),
        context=context,
        release_info=build_series_release_info(media_input),
    )


@pytest.fixture
def movie_context() -> _UploadFixture:
    file_path = Path("Movie.2024.1080p.WEB-DL.H.264-GRP.mkv")
    media_input = MediaInputPayload(
        input_path=file_path,
        media_type=MediaType.MOVIE,
        file_list=[file_path],
        file_list_mediainfo={file_path: _mediainfo_obj()},
    )
    context = ProcessingContext(
        media_input=media_input,
        media_search=MediaSearchPayload(media_type=MediaType.MOVIE),
    )
    return _UploadFixture(
        torrent_file=Path("release.torrent"),
        context=context,
        release_info=build_series_release_info(media_input),
    )


@pytest.mark.parametrize("tracker", sorted(UNSUPPORTED_SERIES_TRACKERS, key=str))
def test_series_upload_is_refused_for_every_unsupported_tracker(
    tracker: TrackerSelection, series_context: _UploadFixture
) -> None:
    """`process.py:1607` is the only thing stopping a real upload attempt."""
    backend = _process_backend()

    with pytest.raises(TrackerError, match="does not support series uploads"):
        backend.upload(
            tracker=tracker,
            torrent_file=series_context.torrent_file,
            nfo="",
            tracker_title="Show S01",
            context=series_context.context,
            release_info=series_context.release_info,
        )


def test_a_supporting_tracker_passes_the_series_guard(
    series_context: _UploadFixture,
) -> None:
    """The guard must not fire for a tracker that does support series."""
    supported = next(
        tracker
        for tracker in TrackerSelection
        if tracker not in UNSUPPORTED_SERIES_TRACKERS
    )
    backend = _process_backend()

    with pytest.raises(TrackerError) as excinfo:
        backend.upload(
            tracker=supported,
            torrent_file=series_context.torrent_file,
            nfo="",
            tracker_title="Show S01",
            context=series_context.context,
            release_info=series_context.release_info,
        )

    # Anything raised past the guard is a downstream concern (credentials).
    assert "does not support series uploads" not in str(excinfo.value)


def test_a_movie_upload_is_never_blocked_by_the_series_guard(
    movie_context: _UploadFixture,
) -> None:
    backend = _process_backend()

    for tracker in sorted(UNSUPPORTED_SERIES_TRACKERS, key=str):
        with pytest.raises(TrackerError) as excinfo:
            backend.upload(
                tracker=tracker,
                torrent_file=movie_context.torrent_file,
                nfo="",
                tracker_title="Movie 2024",
                context=movie_context.context,
                release_info=movie_context.release_info,
            )
        assert "does not support series uploads" not in str(excinfo.value)


def test_dupe_check_queues_a_placeholder_for_an_unsupported_series_tracker(
    series_context: _UploadFixture,
) -> None:
    """`process.py:153` is the dupe-check counterpart of the upload guard:
    for a series release it must append `_unsupported_series_tracker_dupe`'s
    placeholder instead of running a real search against the tracker."""
    backend = _process_backend()

    results = asyncio.run(
        backend.dupe_checks(
            processing_queue=[TrackerSelection.PASS_THE_POPCORN],
            media_input_payload=series_context.context.media_input,
            media_search_payload=series_context.context.media_search,
        )
    )

    assert results[TrackerSelection.PASS_THE_POPCORN] == (
        TrackerSelection.PASS_THE_POPCORN,
        False,
        "PassThePopcorn does not support series uploads yet",
    )
