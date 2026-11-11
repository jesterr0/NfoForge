"""A full disc reaches each tracker as a disc, decided once from the disc."""

from pathlib import Path
from typing import Any, cast

from pymediainfo import MediaInfo
import pytest

from nfoforge.backend.process import upload_disc_release
from nfoforge.backend.trackers.beyondhd import BHDUploader, bhd_disc_type
from nfoforge.backend.trackers.hdb import HDBUploader, hdb_medium_id
from nfoforge.backend.trackers.media_support import (
    DISCS_UNCONFIRMED,
    TRACKER_SUPPORTED_DISCS,
    supports_disc,
    unsupported_trackers,
)
from nfoforge.backend.trackers.onlyencodes import OnlyEncodesUploader
from nfoforge.backend.trackers.torrentleech import TLUploader
from nfoforge.backend.trackers.unit3d_base import Unit3dBaseUploader
from nfoforge.backend.trackers.unit3d_ids import (
    _DISTRIBUTOR_BY_NAME,  # pyright: ignore[reportPrivateUsage]
    UNIT3D_DISTRIBUTORS,
    unit3d_distributor_id,
    unit3d_region_id,
)
from nfoforge.core.disc import (
    Disc,
    DiscRelease,
    DiscSize,
    DiscType,
    disc_release,
    parse_bdinfo_report,
)
from nfoforge.core.trackers.validate import disc_unsupported_trackers
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.enums.trackers.aither import AitherCategory, AitherResolution, AitherType
from nfoforge.enums.trackers.beyondhd import BHDType
from nfoforge.enums.trackers.hdb import HDBMedium
from nfoforge.enums.trackers.torrentleech import TLCategories
from nfoforge.exceptions import TrackerError

FIXTURES = Path(__file__).parents[1] / "fixtures" / "bdinfo"
BLURAY = DiscRelease(
    DiscType.BDMV, DiscSize.BD25, uhd=False, bdinfo_summary="Disc Title: X"
)
UHD = DiscRelease(DiscType.BDMV, DiscSize.BD66, uhd=True, bdinfo_summary="UHD")
DVD = DiscRelease(
    DiscType.DVD,
    DiscSize.DVD9,
    uhd=False,
    ifo_mediainfo="IFO report",
    vob_mediainfo="VOB report",
)


def _disc(tmp_path: Path, disc_type: DiscType = DiscType.BDMV) -> Disc:
    report = (FIXTURES / "bdinfo_rs_5.0.0_bluray_avc_lpcm.txt").read_text(
        encoding="utf-8"
    )
    return Disc(
        root=tmp_path / "Movie 1990 1080p GBR Blu-ray AVC LPCM 2.0-GRP",
        disc_type=disc_type,
        label="MOVIE",
        size=30_000_000_000,
        bdinfo=parse_bdinfo_report(report) if disc_type is DiscType.BDMV else None,
        ifo_mediainfo="IFO" if disc_type is DiscType.DVD else "",
    )


def test_the_release_is_read_from_the_disc(tmp_path: Path) -> None:
    disc = _disc(tmp_path)

    release = disc_release(disc, None, region=" GBR ", distributor="Arrow")

    assert release.is_bluray
    assert release.size_class is DiscSize.BD50
    assert not release.uhd
    assert release.bdinfo_summary.startswith("Disc Label:")
    assert (release.region, release.distributor) == ("GBR", "Arrow")


@pytest.mark.parametrize(
    ("release", "expected"),
    [
        (BLURAY, BHDType.BD_25),
        (DiscRelease(DiscType.BDMV, DiscSize.BD50, uhd=False), BHDType.BD_50),
        (DiscRelease(DiscType.BDMV, DiscSize.BD50, uhd=True), BHDType.UHD_50),
        (UHD, BHDType.UHD_66),
        (DiscRelease(DiscType.BDMV, DiscSize.BD100, uhd=True), BHDType.UHD_100),
        (DVD, BHDType.DVD_9),
    ],
)
def test_beyondhd_type_is_the_size_class(
    release: DiscRelease, expected: BHDType
) -> None:
    assert bhd_disc_type(release) is expected


def test_beyondhd_refuses_a_disc_size_it_has_no_type_for() -> None:
    with pytest.raises(TrackerError, match="UHD BD25"):
        bhd_disc_type(DiscRelease(DiscType.BDMV, DiscSize.BD25, uhd=True))


def test_beyondhd_sends_the_bdinfo_summary_as_mediainfo(tmp_path: Path) -> None:
    uploader = BHDUploader(
        api_key="key",
        torrent_file=tmp_path / "x.torrent",
        # a folder name that says nothing about the disc
        input_path=tmp_path / "Some Folder",
        media_type=MediaType.MOVIE,
        disc=BLURAY,
    )

    assert uploader._type() == BHDType.BD_25.value
    assert uploader._source() == "Blu-ray"
    assert uploader._cleaned_media_info() == "Disc Title: X"


def _unit3d(tmp_path: Path, cls: type[Unit3dBaseUploader] = Unit3dBaseUploader) -> Any:
    kwargs: dict[str, Any] = {
        "media_type": MediaType.MOVIE,
        "api_key": "key",
        "torrent_file": tmp_path / "x.torrent",
        "input_path": tmp_path / "Some Folder",
        "mediainfo_obj": cast(MediaInfo, object()),
    }
    if cls is Unit3dBaseUploader:
        kwargs.update(
            tracker_name=TrackerSelection.AITHER,
            base_url="https://tracker.example",
            cat_enum=AitherCategory,
            res_enum=AitherResolution,
            type_enum=AitherType,
        )
    return cls(**kwargs)


def test_unit3d_sends_a_bluray_as_bdinfo_with_no_mediainfo(tmp_path: Path) -> None:
    uploader = _unit3d(tmp_path)

    assert uploader._get_type_id(BLURAY) == AitherType.DISC.value
    assert uploader._technical_fields(BLURAY, "nfo") == {
        "mediainfo": "",
        "bdinfo": "Disc Title: X",
    }


def test_unit3d_sends_a_dvd_ifo_with_the_vob_in_the_description(
    tmp_path: Path,
) -> None:
    fields = _unit3d(tmp_path)._technical_fields(DVD, "the nfo")

    assert fields == {
        "mediainfo": "IFO report",
        "description": "the nfo\n\n[code]VOB report[/code]",
    }


def test_unit3d_refuses_a_bluray_with_no_bdinfo(tmp_path: Path) -> None:
    with pytest.raises(TrackerError, match="BDInfo"):
        _unit3d(tmp_path)._technical_fields(
            DiscRelease(DiscType.BDMV, DiscSize.BD25, uhd=False), "nfo"
        )


def test_a_file_named_like_a_disc_is_not_typed_as_one(tmp_path: Path) -> None:
    # the name alone no longer makes a release a full disc
    uploader = _unit3d(tmp_path)
    uploader.input_path = tmp_path / "Movie.2024.1080p.BluRay.AVC-GRP.mkv"

    with pytest.raises(TrackerError, match="Type ID"):
        uploader._get_type_id()


def test_onlyencodes_refuses_a_disc(tmp_path: Path) -> None:
    with pytest.raises(TrackerError, match="full discs"):
        _unit3d(tmp_path, OnlyEncodesUploader)._get_type_id(BLURAY)


def test_hdbits_takes_a_bluray_with_empty_techinfo(tmp_path: Path) -> None:
    uploader = HDBUploader(
        username="u",
        passkey="p",
        session_cookie="c",
        torrent_file=tmp_path / "x.torrent",
        input_path=tmp_path / "Some Folder",
        media_type=MediaType.MOVIE,
        mediainfo_obj=cast(MediaInfo, object()),
    )

    assert hdb_medium_id(tmp_path, BLURAY) == HDBMedium.BLURAY.value
    assert uploader._techinfo(BLURAY) == ""
    with pytest.raises(TrackerError, match="DVD"):
        hdb_medium_id(tmp_path, DVD)


@pytest.mark.parametrize(
    ("release", "expected"),
    [
        (BLURAY, TLCategories.MOVIE_BLURAY),
        (UHD, TLCategories.MOVIE_4K),
        (DVD, TLCategories.MOVIE_DVD),
    ],
)
def test_torrentleech_files_a_disc_under_its_disc_category(
    release: DiscRelease, expected: TLCategories
) -> None:
    category = TLUploader._detect_category(
        "Some Folder", "1080p", MediaType.MOVIE, disc=release
    )
    assert category == expected.value


def test_every_tracker_states_which_discs_it_takes() -> None:
    assert set(TRACKER_SUPPORTED_DISCS) == set(TrackerSelection)
    assert supports_disc(TrackerSelection.HDB, DiscType.BDMV)
    assert not supports_disc(TrackerSelection.HDB, DiscType.DVD)
    assert not supports_disc(TrackerSelection.ONLY_ENCODES, DiscType.BDMV)
    # a tracker whose rules are unchecked is sent no disc at all
    for tracker in DISCS_UNCONFIRMED:
        assert TRACKER_SUPPORTED_DISCS[tracker] == frozenset()


def test_unsupported_trackers_say_why() -> None:
    reasons = unsupported_trackers(MediaType.SERIES, DiscType.DVD)

    assert "series" in reasons[TrackerSelection.PASS_THE_POPCORN]
    assert reasons[TrackerSelection.BLUTOPIA].endswith("full DVD disc.")
    assert "not been checked" in reasons[TrackerSelection.AITHER]
    assert TrackerSelection.BEYOND_HD not in reasons
    assert disc_unsupported_trackers(
        [TrackerSelection.HDB, TrackerSelection.BEYOND_HD], DiscType.DVD
    ) == [TrackerSelection.HDB]
    assert disc_unsupported_trackers([TrackerSelection.HDB], None) == []


class _Context:
    def __init__(self, media_input: Any, overrides: dict[str, str] | None) -> None:
        self.media_input = media_input
        dynamic = {} if overrides is None else {"override_tokens": overrides}
        self.shared_data = type("Shared", (), {"dynamic_data": dynamic})()


class _MediaInput:
    def __init__(self, disc: Disc | None) -> None:
        self.discs = [disc] if disc else []

    def primary_media_file(self) -> None:
        return None

    def release_name(self) -> str:
        return "Movie 1990 1080p GBR Blu-ray AVC LPCM 2.0-GRP"


def test_upload_region_is_the_override_even_when_blank(tmp_path: Path) -> None:
    disc = _disc(tmp_path)

    detected = upload_disc_release(_Context(_MediaInput(disc), None))  # type: ignore[arg-type]
    cleared = upload_disc_release(_Context(_MediaInput(disc), {"region": ""}))  # type: ignore[arg-type]
    loose_files = upload_disc_release(_Context(_MediaInput(None), None))  # type: ignore[arg-type]

    assert detected is not None
    assert detected.region == "GBR"
    assert cleared is not None
    assert cleared.region == ""
    assert loose_files is None


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("Arrow", 75),
        ("Arrow Video", 75),
        ("Criterion Collection", 218),
        ("Shout! Factory", 772),
        ("warner bros", 935),
        ("Hannsler Classic", 416),
        ("Disney/Buena Vista", 253),
        ("Radiance Films", 966),
        ("Capitol", 158),
        ("Capitol Records", 159),
        # a shorter name never picks between longer ones
        ("Warner", None),
        ("", None),
    ],
)
def test_a_typed_distributor_finds_its_unit3d_id(
    typed: str, expected: int | None
) -> None:
    assert unit3d_distributor_id(typed) == expected


def test_every_distributor_name_is_distinct_once_normalised() -> None:
    assert len(_DISTRIBUTOR_BY_NAME) == len(UNIT3D_DISTRIBUTORS) == 966


def test_unit3d_sends_region_and_distributor_ids_that_resolve(
    tmp_path: Path,
) -> None:
    disc = DiscRelease(
        DiscType.BDMV,
        DiscSize.BD25,
        uhd=False,
        region="gbr",
        distributor="Nobody Films",
    )

    assert unit3d_region_id("GBR") == 78
    assert _unit3d(tmp_path)._disc_ids(disc) == {"region_id": 78}
    assert _unit3d(tmp_path)._disc_ids(None) == {}


def test_trackers_not_yet_confirmed_get_no_disc_ids(tmp_path: Path) -> None:
    uploader = _unit3d(tmp_path)
    uploader.tracker_name = TrackerSelection.UTOPIA
    disc = DiscRelease(DiscType.BDMV, DiscSize.BD25, uhd=False, region="USA")

    assert uploader._disc_ids(disc) == {}
