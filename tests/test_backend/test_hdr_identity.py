import inspect

from pymediainfo import MediaInfo
import pytest

from src.backend.utils.hdr_identity import resolve_hdr_identity
from src.config.models import HdrType


def _dynamic_range_media_info(hdr_format: str = "", transfer: str = "") -> MediaInfo:
    # HDR_Format is emitted twice, as real MediaInfo does: the raw value
    # first, the human-readable string second. pymediainfo puts the first
    # occurrence in `hdr_format` and the rest in `other_hdr_format`, and the
    # function under test reads `other_hdr_format[0]`. A single element
    # leaves that attribute None and no HDR is detected at all.
    hdr_xml = (
        f"<HDR_Format>{hdr_format}</HDR_Format><HDR_Format>{hdr_format}</HDR_Format>"
        if hdr_format
        else ""
    )
    transfer_xml = (
        f"<transfer_characteristics>{transfer}</transfer_characteristics>"
        if transfer
        else ""
    )
    return MediaInfo(
        f"""<Mediainfo><File>
        <track type="General"><Duration>60000</Duration><File_size>1000</File_size></track>
        <track type="Video"><Width>3840</Width><Height>2160</Height><Scan_type>Progressive</Scan_type><Frame_rate>24.000</Frame_rate><Format>HEVC</Format>{hdr_xml}{transfer_xml}</track>
        <track type="Audio"><Format>AC-3</Format><Channel_s>2</Channel_s><Language>en</Language></track>
        </File></Mediainfo>"""
    )


# The strings MediaInfo actually reports, kept verbatim. Abbreviating one
# would test a spelling no file carries: "SMPTE ST 2094 App 4" is what makes
# a stream HDR10+, and its "HDR10+" substring contains "HDR10", which is the
# collision the resolver has to get right.
HDR10 = "SMPTE ST 2086, HDR10 compatible"
HDR10_PLUS = "SMPTE ST 2094 App 4, Version 1, HDR10+ Profile B compatible"
DV_PROFILE_5 = "Dolby Vision, Version 1.0, dvhe.05.06, BL+RPU"
DV_PROFILE_8 = "Dolby Vision, Version 1.0, dvhe.08.06, BL+RPU, HDR10 compatible"
DV_HDR10 = f"{DV_PROFILE_8} / {HDR10}"
DV_HDR10_PLUS = f"{DV_PROFILE_8} / {HDR10_PLUS}"


def test_the_fixture_populates_other_hdr_format() -> None:
    """Guards the fixture, not the resolver.

    A single <HDR_Format> element leaves `other_hdr_format` None, the
    resolver sees no HDR at all, and every HDR case below would then pass or
    fail for a reason that has nothing to do with the code under test.
    """
    track = _dynamic_range_media_info(HDR10, "PQ").video_tracks[0]

    assert track.other_hdr_format == [HDR10]


@pytest.mark.parametrize(
    ("hdr_format", "transfer", "expected"),
    [
        ("", "", "SDR"),
        ("", "BT.709", "SDR"),
        ("", "PQ", "PQ"),
        ("", "HLG", "HLG"),
        (HDR10, "PQ", "HDR10"),
        (HDR10_PLUS, "PQ", "HDR10+"),
        (DV_PROFILE_5, "PQ", "DV"),
        (DV_HDR10, "PQ", "DV HDR10"),
        (DV_HDR10_PLUS, "PQ", "DV HDR10+"),
    ],
    ids=[
        "nothing",
        "sdr-transfer",
        "pq",
        "hlg",
        "hdr10",
        "hdr10-plus",
        "dv-profile-5",
        "dv-hdr10",
        "dv-hdr10-plus",
    ],
)
def test_each_media_info_signal_resolves_to_one_identity(
    hdr_format: str, transfer: str, expected: HdrType
) -> None:
    identity = resolve_hdr_identity(_dynamic_range_media_info(hdr_format, transfer))

    assert identity == expected


def test_every_identity_is_reachable() -> None:
    """All eight values of HdrType must be producible from MediaInfo alone.

    An identity nothing can resolve to is one a tracker rule can never fire
    on, and it would go unnoticed because no test would fail.
    """
    resolved = {
        resolve_hdr_identity(_dynamic_range_media_info(hdr_format, transfer))
        for hdr_format, transfer in (
            ("", ""),
            ("", "PQ"),
            ("", "HLG"),
            (HDR10, "PQ"),
            (HDR10_PLUS, "PQ"),
            (DV_PROFILE_5, "PQ"),
            (DV_HDR10, "PQ"),
            (DV_HDR10_PLUS, "PQ"),
        )
    }

    assert resolved == {
        "SDR",
        "PQ",
        "HLG",
        "HDR10",
        "HDR10+",
        "DV",
        "DV HDR10",
        "DV HDR10+",
    }


def test_no_media_info_is_sdr() -> None:
    """SDR is the absence of an HDR signal, not a separate signal.

    A file that could not be read has no dynamic range to state, and a
    tracker title needs a value rather than an error.
    """
    assert resolve_hdr_identity(None) == "SDR"


def test_no_video_track_is_sdr() -> None:
    media_info = MediaInfo(
        """<Mediainfo><File>
        <track type="General"><Duration>60000</Duration></track>
        <track type="Audio"><Format>AC-3</Format></track>
        </File></Mediainfo>"""
    )

    assert resolve_hdr_identity(media_info) == "SDR"


def test_hdr10_plus_wins_over_its_own_hdr10_substring() -> None:
    """HDR10+ contains HDR10 as a substring, so check order is load-bearing.

    The tracker rule that drops an assumed HDR10 baseline must leave HDR10+
    alone, which it can only do if HDR10+ never resolves to HDR10.
    """
    assert resolve_hdr_identity(_dynamic_range_media_info(HDR10_PLUS, "PQ")) == "HDR10+"
    assert (
        resolve_hdr_identity(_dynamic_range_media_info(DV_HDR10_PLUS, "PQ"))
        == "DV HDR10+"
    )


def test_dolby_vision_profile_8_carries_hdr10_even_unspelled() -> None:
    """Profile 5 is the only Dolby Vision profile with no HDR10 base layer.

    MediaInfo does not always append the "HDR10 compatible" half, so the
    profile is the signal and the spelling is not.
    """
    unspelled = "Dolby Vision, Version 1.0, dvhe.08.06, BL+RPU"

    assert (
        resolve_hdr_identity(_dynamic_range_media_info(unspelled, "PQ")) == "DV HDR10"
    )


def test_an_unrecognised_hdr_format_falls_back_to_transfer_characteristics() -> None:
    """A mastering-display tag alone names no format, but PQ is still PQ.

    Claiming HDR10 off "SMPTE ST 2086" would overstate what the file says;
    claiming SDR would understate it.
    """
    assert (
        resolve_hdr_identity(_dynamic_range_media_info("SMPTE ST 2086", "PQ")) == "PQ"
    )


def test_identity_ignores_the_user_dynamic_range_settings() -> None:
    """A tracker rule cannot be subject to a user toggle.

    DynamicRangeSettings blanks the component by resolution or by type,
    which is a filename preference. One tracker requires SDR on a 2160p WEB
    release from a user who has SDR switched off, so identity must not be
    able to see those switches at all.
    """
    parameters = inspect.signature(resolve_hdr_identity).parameters

    assert list(parameters) == ["media_info"]
