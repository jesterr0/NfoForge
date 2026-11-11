"""How a full disc is named: region, PAL/NTSC, size class, untouched codec."""

from pathlib import Path

from pymediainfo import MediaInfo
import pytest

from nfoforge.backend.token_replacer import TokenReplacer
from nfoforge.backend.tokens import FileToken, NfoToken, TokenData
from nfoforge.config.models import (
    DEFAULT_BLURAY_NAME_TEMPLATE,
    DEFAULT_DVD_NAME_TEMPLATE,
)
from nfoforge.core.disc import (
    Disc,
    choose_playlist,
    detect_disc,
    detect_region,
    disc_quality,
    dvd_standard,
    parse_bdinfo_report,
)
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.rename import QualitySelection
from nfoforge.enums.token_replacer import UnfilledTokenRemoval
from nfoforge.payloads.media_inputs import MediaInputPayload
from nfoforge.payloads.media_search import MediaSearchPayload
from tests.disc_helpers import make_bluray, make_dvd

REAL_REPORT = (
    Path(__file__).parents[1]
    / "fixtures"
    / "bdinfo"
    / "bdinfo_rs_5.0.0_bluray_avc_lpcm.txt"
).read_text(encoding="utf-8")


def _mediainfo(
    *, video_format: str = "AVC", height: int = 1080, standard: str = ""
) -> MediaInfo:
    width = {1080: 1920, 2160: 3840}.get(height, 720)
    standard_xml = f"<Standard>{standard}</Standard>" if standard else ""
    return MediaInfo(
        f"""<Mediainfo><File>
        <track type="General"><Duration>60000</Duration><File_size>1000</File_size></track>
        <track type="Video"><Format>{video_format}</Format><Width>{width}</Width><Height>{height}</Height><Scan_type>Progressive</Scan_type><Frame_rate>23.976</Frame_rate>{standard_xml}</track>
        <track type="Audio"><Format>PCM</Format><Channel_s>2</Channel_s><Channel_s>2 channels</Channel_s><Language>en</Language></track>
        </File></Mediainfo>"""
    )


def _bluray(root: Path, label: str = "") -> Disc:
    folder = root / label if label else root
    disc = detect_disc(
        make_bluray(folder, {"00800": [("00001", 0, 7200)]}, {"00001": 9})
    )
    assert disc is not None
    choose_playlist(disc)
    return disc


# --------------------------------------------------------------------------
# region, standard, quality
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("folder", "expected"),
    [
        ("Men at Work 1990 1080p GBR Blu-ray AVC LPCM 2.0-Liber8", "GBR"),
        ("Men.at.Work.1990.1080p.Blu-ray.AVC-GRP", ""),
        # a title word is never a region, only what follows the year
        ("Yes We CAN 2012 1080p Blu-ray AVC-GRP", ""),
        ("CAN 2012 1080p CAN Blu-ray AVC-GRP", "CAN"),
        ("No Year Here GBR", ""),
    ],
)
def test_region_is_read_after_the_year(
    tmp_path: Path, folder: str, expected: str
) -> None:
    assert detect_region(_bluray(tmp_path, "disc"), folder) == expected


def test_region_is_read_from_the_last_word_of_the_label(tmp_path: Path) -> None:
    disc = _bluray(tmp_path)
    disc.label = "MEN_AT_WORK_USA"
    assert detect_region(disc, "Men at Work") == "USA"
    disc.label = "MAD_MAX"
    assert detect_region(disc, "Mad Max") == ""


def test_dvd_standard_is_stated_or_read_from_the_height() -> None:
    assert dvd_standard(_mediainfo(height=576, standard="PAL")) == "PAL"
    assert dvd_standard(_mediainfo(height=480)) == "NTSC"
    assert dvd_standard(_mediainfo(height=576)) == "PAL"
    assert dvd_standard(_mediainfo(height=720)) == ""
    assert dvd_standard(None) == ""


def test_disc_quality_is_the_medium(tmp_path: Path) -> None:
    disc = _bluray(tmp_path / "bd")
    assert disc_quality(disc, _mediainfo()) is QualitySelection.BLURAY
    uhd = _mediainfo(video_format="HEVC", height=2160)
    assert disc_quality(disc, uhd) is QualitySelection.UHD_BLURAY

    dvd = detect_disc(make_dvd(tmp_path / "dvd", {"01": [1, 100]}, ifos=False))
    assert dvd is not None
    assert disc_quality(dvd, _mediainfo(height=576)) is QualitySelection.DVD


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------
def _payload(disc: Disc, mediainfo: MediaInfo, folder_name: str) -> MediaInputPayload:
    primary = disc.primary_media_file()
    assert primary is not None
    return MediaInputPayload(
        input_path=disc.root.parent / folder_name,
        media_type=MediaType.MOVIE,
        file_list=[primary],
        file_list_mediainfo={primary: mediainfo},
        input_kind="directory",
        content_size=disc.size,
        discs=[disc],
    )


def _render(
    payload: MediaInputPayload,
    template: str,
    overrides: dict[str, str] | None = None,
    token_type: type = FileToken,
) -> str:
    output = TokenReplacer(
        media_input_obj=payload,
        token_string=template,
        media_search_obj=MediaSearchPayload(
            media_type=MediaType.MOVIE, title="Men at Work", year=1990
        ),
        flatten=True,
        file_name_mode=token_type is FileToken,
        append_suffix=False,
        token_type=token_type,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        override_tokens=dict(overrides or {}),
    ).get_output()
    return output or ""


def test_a_bluray_is_named_as_an_untouched_disc(tmp_path: Path) -> None:
    disc = _bluray(tmp_path, "disc")
    payload = _payload(
        disc, _mediainfo(), "Men at Work 1990 1080p GBR Blu-ray AVC LPCM 2.0-Liber8"
    )

    name = _render(
        payload,
        DEFAULT_BLURAY_NAME_TEMPLATE,
        {"source": "BluRay", "release_group": "Liber8"},
    )

    # the medium's spelling and the stream's own codec name, never "x264"
    assert name == "Men.at.Work.1990.1080p.GBR.Blu-ray.AVC.LPCM.2.0-Liber8"


def test_a_region_typed_by_the_user_beats_the_one_read(tmp_path: Path) -> None:
    disc = _bluray(tmp_path, "disc")
    payload = _payload(disc, _mediainfo(), "Movie 1990 1080p GBR Blu-ray")
    assert _render(payload, "{region}", {"region": "EUR"}) == "EUR"
    assert _render(payload, "{region} {distributor}") == "GBR"
    assert _render(payload, "{distributor}", {"distributor": "Criterion"}) == (
        "Criterion"
    )


def test_a_dvd_is_named_by_standard_and_size(tmp_path: Path) -> None:
    dvd = detect_disc(make_dvd(tmp_path / "dvd", {"01": [1, 100]}, ifos=False))
    assert dvd is not None
    choose_playlist(dvd)
    payload = _payload(dvd, _mediainfo(video_format="MPEG Video", height=576), "x")

    name = _render(payload, DEFAULT_DVD_NAME_TEMPLATE, {"release_group": "GRP"})

    assert name == "Men.at.Work.1990.PAL.DVD5.LPCM.2.0-GRP"


def test_disc_tokens_are_empty_for_a_file() -> None:
    media = Path("Movie.2020.1080p.BluRay.x264-GRP.mkv")
    payload = MediaInputPayload(
        input_path=media,
        file_list=[media],
        file_list_mediainfo={media: _mediainfo()},
    )
    assert _render(payload, "{region}{disc_size}{dvd_standard}") == ""
    assert _render(payload, "{source}", {"source": "BluRay"}) == "BluRay"


def test_the_disc_reports_reach_the_nfo(tmp_path: Path) -> None:
    disc = _bluray(tmp_path, "disc")
    disc.bdinfo = parse_bdinfo_report(REAL_REPORT)
    disc.ifo_mediainfo = "ifo text"
    replacer = TokenReplacer(
        media_input_obj=_payload(disc, _mediainfo(), "Men at Work 1990"),
        token_string="",
        flatten=True,
        token_type=NfoToken,
    )

    def value(token: str) -> object:
        return replacer._get_raw_token_value(
            TokenData(bracket_token=f"{{{token}}}", pre_token="", post_token="")
        )

    assert value("bdinfo_summary") == disc.bdinfo.quick_summary
    assert value("bdinfo_full") == REAL_REPORT
    # a Blu-ray has no DVD reports; an empty one is left out
    assert value("dvd_ifo_mediainfo") == "ifo text"
    assert value("dvd_vob_mediainfo") == ""
