from pathlib import Path
from typing import cast

import pytest
from pymediainfo import MediaInfo

from src.backend.trackers.aither import AitherUploader
from src.backend.trackers.beyondhd import BHDUploader
from src.backend.trackers.morethantv import MTVUploader
from src.backend.trackers.series_support import (
    UNSUPPORTED_SERIES_TRACKERS,
    supports_series_upload,
)
from src.backend.trackers.torrentleech import TLUploader
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
