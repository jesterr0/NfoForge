import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import inspect
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

from pymediainfo import MediaInfo
import pytest

from src.backend.process import ProcessBackEnd
from src.backend.trackers.aither import AitherUploader
from src.backend.trackers.beyondhd import BHDUploader
from src.backend.trackers.blutopia import BlutopiaUploader
from src.backend.trackers.darkpeers import DarkPeersUploader
from src.backend.trackers.fearnopeer import FearNoPeerUploader
from src.backend.trackers.huno import HunoUploader, huno_uploader
from src.backend.trackers.lst import LSTUploader
from src.backend.trackers.media_support import (
    TRACKER_SUPPORTED_MEDIA,
    UNIT3D_TRACKERS,
    UNSUPPORTED_MOVIE_TRACKERS,
    UNSUPPORTED_SERIES_TRACKERS,
    supports_media,
    supports_series_upload,
)
from src.backend.trackers.onlyencodes import OnlyEncodesUploader
from src.backend.trackers.passthepopcorn import ptp_uploader
from src.backend.trackers.reelflix import ReelFlixUploader
from src.backend.trackers.seedpool import SeedPoolUploader
from src.backend.trackers.shareisland import ShareIslandUploader
from src.backend.trackers.title_rules import accepts_a_release_name
from src.backend.trackers.torrentleech import TLUploader
from src.backend.trackers.unit3d_base import Unit3dBaseUploader
from src.backend.trackers.uploadcx import UploadCXUploader
from src.backend.trackers.utp import UTPUploader
from src.backend.trackers.yuscene import YuSceneUploader
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
from src.enums.trackers.torrentleech import TLCategories
from src.exceptions import TrackerError
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.payloads.series import SeriesReleaseInfo, build_series_release_info


@pytest.mark.parametrize(
    ("tracker", "expected"),
    [
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
        (TrackerSelection.BLUTOPIA, True),
        (TrackerSelection.SEEDPOOL, True),
        (TrackerSelection.UTOPIA, True),
        (TrackerSelection.YU_SCENE, True),
        (TrackerSelection.FEAR_NO_PEER, True),
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
        BlutopiaUploader,
        SeedPoolUploader,
        UTPUploader,
        YuSceneUploader,
        FearNoPeerUploader,
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


def test_unit3d_season_pack_payload_sends_episode_zero(
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

    # UNIT3D requires episode_number on every TV-category upload -- there is no
    # season-pack exemption in StoreTorrentRequest -- and expresses a pack as
    # episode 0 (TorrentMeta renders 0 as "Season Pack", anything else as
    # "Episode N"). process.py passes release_info.episode_start through, so
    # this also proves the pack branch overrides a real episode number rather
    # than letting it through and filing the pack under Episodes.
    payload = uploader._build_upload_payload(
        tracker_title=None,
        season_number=1,
        episode_number=1,
        season_pack=True,
    )

    assert payload["season_number"] == 1
    assert payload["episode_number"] == 0
    assert payload["season_pack"] == 1


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
    backend.config.settings.trackers.torrent_leech.torrent_passkey = ""
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


@pytest.fixture
def unresolved_series_context() -> _UploadFixture:
    """A series whose season/episode could not be resolved from the mapping
    *or* the filename -- the date-based shape that reached UNIT3D with both
    fields silently absent from the payload."""
    file_path = Path("The.Daily.Show.2024.01.15.1080p.WEB.h264-GRP.mkv")
    media_input = MediaInputPayload(
        input_path=file_path,
        media_type=MediaType.SERIES,
        file_list=[file_path],
        file_list_mediainfo={file_path: _mediainfo_obj()},
        series_episode_map={file_path: {"season": None, "episode": None}},
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


@pytest.mark.parametrize(
    "tracker",
    sorted(UNIT3D_TRACKERS - UNSUPPORTED_SERIES_TRACKERS, key=str),
)
def test_unit3d_series_upload_is_refused_without_a_season_or_episode(
    tracker: TrackerSelection, unresolved_series_context: _UploadFixture
) -> None:
    """UNIT3D marks season_number/episode_number required on every TV-category
    upload, so an unresolved release must fail here rather than going out with
    the fields dropped. Backstops the Series Match page guard for entry points
    that skip it (the sandbox wizard, restored jobs)."""
    backend = _process_backend()

    with pytest.raises(TrackerError, match="Could not determine"):
        backend.upload(
            tracker=tracker,
            torrent_file=unresolved_series_context.torrent_file,
            nfo="",
            tracker_title="The Daily Show",
            context=unresolved_series_context.context,
            release_info=unresolved_series_context.release_info,
        )


@pytest.mark.parametrize(
    ("tracker", "dispatch"),
    [
        (TrackerSelection.TORRENT_LEECH, "src.backend.process.tl_upload"),
        (TrackerSelection.BEYOND_HD, "src.backend.process.bhd_uploader"),
        (TrackerSelection.HDB, "src.backend.process.hdb_uploader"),
    ],
)
def test_non_unit3d_series_uploads_are_not_blocked_by_the_episode_guard(
    tracker: TrackerSelection, dispatch: str, unresolved_series_context: _UploadFixture
) -> None:
    """These trackers either don't send a season/episode at all (TorrentLeech,
    BeyondHD) or treat them as optional (HDBits' tvdb_season/tvdb_episode), so
    the UNIT3D requirement must not regress uploads that work today without
    one. Patching the dispatch proves the call reached the tracker rather than
    inferring it from whichever downstream error happened to surface."""
    backend = _process_backend()
    # `_process_backend` blanks this so the guard tests stop at "missing
    # credentials"; here the call has to get all the way to the dispatch.
    backend.config.settings.trackers.torrent_leech.torrent_passkey = "passkey"

    with patch(dispatch, return_value=True) as dispatched:
        backend.upload(
            tracker=tracker,
            torrent_file=unresolved_series_context.torrent_file,
            nfo="",
            tracker_title="The Daily Show",
            context=unresolved_series_context.context,
            release_info=unresolved_series_context.release_info,
        )

    assert dispatched.call_count == 1


def test_a_resolved_series_upload_passes_the_episode_guard(
    series_context: _UploadFixture,
) -> None:
    """The guard must not fire on the normal SxxExx path."""
    backend = _process_backend()

    with patch("src.backend.process.aither_uploader", return_value=True) as dispatched:
        backend.upload(
            tracker=TrackerSelection.AITHER,
            torrent_file=series_context.torrent_file,
            nfo="",
            tracker_title="Show S01E01",
            context=series_context.context,
            release_info=series_context.release_info,
        )

    assert dispatched.call_count == 1
    assert dispatched.call_args.kwargs["season_number"] == 1
    assert dispatched.call_args.kwargs["episode_number"] == 1


def test_unit3d_trackers_lists_every_unit3d_uploader(tmp_path: Path) -> None:
    """UNIT3D_TRACKERS is hand-maintained (there is no tracker -> uploader
    registry to derive it from), so a newly added UNIT3D tracker could be
    silently omitted and skip the season/episode guard. Recover the truth from
    the uploaders themselves: every Unit3dBaseUploader subclass names its own
    TrackerSelection.
    """
    discovered = {
        uploader_cls(
            media_type=MediaType.MOVIE,
            api_key="api-key",
            torrent_file=tmp_path / "upload.torrent",
            input_path=tmp_path / "Example.Movie.2024.1080p.WEB-DL.H.264.mkv",
            mediainfo_obj=cast(MediaInfo, object()),
        ).tracker_name
        for uploader_cls in Unit3dBaseUploader.__subclasses__()
    }

    assert discovered == UNIT3D_TRACKERS


def test_no_release_name_field_matches_uploaders_without_title_inputs() -> None:
    """Keep the title-override exclusions tied to the uploader contracts."""
    assert "tracker_title" not in inspect.signature(ptp_uploader).parameters
    assert "tracker_title" not in inspect.signature(huno_uploader).parameters
    assert not accepts_a_release_name(TrackerSelection.PASS_THE_POPCORN)
    assert not accepts_a_release_name(TrackerSelection.HUNO)
