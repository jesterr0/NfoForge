"""The packaged titles must match the naming rules each tracker publishes.

`test_enforced_title_defaults.py` checks that a REQUIRED tracker enforces
*something*. This file checks that what it enforces is *right*: the exact
component order, spelling and separators from each tracker's own wiki.

The templates being pinned, quoted from the rules as saved:

- Aither remux .... Title Year REPACK Resolution Source REMUX HDR VideoCodec
                    AudioCodec Channels Metadata-Crew
- Aither encode ... Title Year REPACK Resolution Source AudioCodec Channels
                    Metadata HDR VideoCodec-Crew
- Aither WEB-DL ... Title Year REPACK Resolution Service WEB-DL AudioCodec
                    Channels Metadata HDR VideoCodec-Tag
- LST disc/remux .. ... Resolution ... SOURCE TYPE Hi10P HDR Vcodec Dub
                    Acodec Channels Object - Tag
- LST encode/web .. ... Resolution ... SOURCE TYPE Dub Acodec Channels Object
                    Hi10P HDR Vcodec - Tag
- ReelFliX 4.1 .... order-free, every required element present, blank tag
                    preferred over a NOGROUP placeholder
- BeyondHD 3.3.9 .. remux/encode/web-dl with no tag must end "-NOGROUP"

Known gaps, deliberately not asserted because NfoForge has no token for them.
Each needs a new token rather than an edit to the packaged defaults:

- Full discs. Aither's Country and LST's Region, plus their disc-specific
  source spellings ("Blu-ray", "NTSC DVD9", "3xDVD9") where `{source}` renders
  "BluRay"/"DVD". Full-disc uploads are not supported yet, so this stays out.
- Language and dub components: FRENCH/JAPANESE, Dual-Audio, Dubbed, ZXX.
- LST-only: Hi10P, 3D, RERip, and "PQ10" where `{video_dynamic_range_type}`
  renders "PQ".
- `{cut}` renders "Directors Cut" and "Extended Cut" where both trackers want
  "Director's Cut" and "Extended". The normalization table behind it is shared
  with filename generation, where an apostrophe is unwanted, so this cannot be
  fixed for titles alone.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.config.config import ConfigManager
from src.config.tv_tokens import SUPPORTED_TVR_FORMATS
from src.enums.token_replacer import UnfilledTokenRemoval
from src.enums.tracker_selection import TrackerSelection
from src.payloads.trackers import TrackerInfo
from tests.test_config.config_tree import build_config_paths

# The release shapes the rules distinguish. Only the *name* matters here: it
# drives the filename attributes (REMUX/HYBRID/REPACK) and the source guess,
# while the mediainfo behind it stays the example payload's.
REMUX_NAME = "Movie.Name.2026.REPACK.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.REMUX-SomeGroup.mkv"
ENCODE_NAME = "Movie.Name.2026.1080p.BluRay.TrueHD.Atmos.7.1.DV.HEVC.x265-SomeGroup.mkv"
WEB_NAME = (
    "Movie.Name.2026.2160p.AMZN.WEB-DL.TrueHD.Atmos.7.1.DV.HEVC.H.265-SomeGroup.mkv"
)


@pytest.fixture(scope="module")
def packaged(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[TrackerSelection, TrackerInfo]:
    """The packaged defaults as the running app sees them.

    Loaded through the real ConfigManager rather than by parsing the TOML, so
    the TrackerSelection -> section-name mapping in src/config/operations.py is
    exercised too.
    """
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    manager = ConfigManager("test", build_config_paths(tmp_path_factory.mktemp("cfg")))
    monkeypatch.undo()
    return manager.defaults.trackers.by_selection()


def _media(name: str):
    path = Path(name)
    return replace(
        EXAMPLE_MEDIA_INPUT_PAYLOAD,
        input_path=path,
        file_list=[path],
        file_list_mediainfo={
            path: next(iter(EXAMPLE_MEDIA_INPUT_PAYLOAD.file_list_mediainfo.values()))
        },
    )


def _render(
    info: TrackerInfo,
    name: str,
    source: str,
    *,
    release_group: str | None = None,
    streaming_service: str | None = None,
    token: str | None = None,
    colon_replace=None,
    replace_map=None,
    **series_kwargs: object,
) -> str:
    """Render a packaged token exactly as generate_tracker_title would.

    The replace map is handed to `override_title_rules`, which is the field
    generate_tracker_title fills, so the rules run in the real place rather
    than being reapplied by the test afterwards.
    """
    overrides: dict[str, str] = {"source": source}
    if release_group is not None:
        overrides["release_group"] = release_group
    if streaming_service is not None:
        overrides["streaming_service"] = streaming_service

    output = TokenReplacer(
        media_input_obj=_media(name),
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        token_string=info.mvr_title_token_override if token is None else token,
        colon_replace=(
            info.mvr_title_colon_replace if colon_replace is None else colon_replace
        ),
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        parse_filename_attributes=True,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        override_tokens=overrides,
        override_title_rules=(
            info.mvr_title_replace_map if replace_map is None else replace_map
        ),
        **series_kwargs,
    ).get_output()

    assert output is not None
    return output


AUDIO_LAST = (TrackerSelection.AITHER, TrackerSelection.LST)


@pytest.mark.parametrize("tracker", AUDIO_LAST)
def test_remux_puts_hdr_and_video_codec_before_the_audio(
    tracker: TrackerSelection, packaged: dict[TrackerSelection, TrackerInfo]
) -> None:
    """Aither: "Source REMUX HDR VideoCodec AudioCodec Channels Metadata".

    Compare Aither's own example, "X-Men: Days of Future Past 2014 2160p UHD
    BluRay REMUX HDR HEVC DTS-HD MA 7.1-FraMeSToR", and LST's, "The Lord of
    the Rings: The Two Towers 2002 2160p UHD BluRay REMUX DV HDR HEVC TrueHD
    7.1 Atmos-FraMeSToR".
    """
    rendered = _render(packaged[tracker], REMUX_NAME, "UHD BluRay")

    assert rendered == (
        "Movie Name 2026 REPACK 2160p UHD BluRay REMUX DV HDR HEVC "
        "TrueHD 7.1 Atmos-SomeGroup"
    )


@pytest.mark.parametrize("tracker", AUDIO_LAST)
def test_encode_puts_the_audio_before_hdr_and_video_codec(
    tracker: TrackerSelection, packaged: dict[TrackerSelection, TrackerInfo]
) -> None:
    """The other half of the split: "Source AudioCodec Channels Metadata HDR
    VideoCodec", as in Aither's "Halo S01 2160p UHD BluRay TrueHD 7.1 Atmos DV
    HDR x265-Stelks"."""
    rendered = _render(packaged[tracker], ENCODE_NAME, "BluRay")

    assert rendered == (
        "Movie Name 2026 2160p BluRay TrueHD 7.1 Atmos DV HDR x265-SomeGroup"
    )


@pytest.mark.parametrize("tracker", AUDIO_LAST)
def test_the_two_orders_come_from_one_packaged_token(
    tracker: TrackerSelection, packaged: dict[TrackerSelection, TrackerInfo]
) -> None:
    """Both orders live in a single template, selected by only_if/unless.

    Pinned separately from the rendering tests so that replacing the mechanism
    with two stored templates, or with a code-side builder, is a deliberate
    decision rather than something these tests quietly accept.
    """
    token = packaged[tracker].mvr_title_token_override

    assert "only_if(remux)" in token
    assert "unless(remux)" in token


ALL_FOUR = (
    TrackerSelection.AITHER,
    TrackerSelection.LST,
    TrackerSelection.REELFLIX,
    TrackerSelection.BEYOND_HD,
)


@pytest.mark.parametrize("tracker", ALL_FOUR)
def test_web_releases_are_spelled_web_dl(
    tracker: TrackerSelection, packaged: dict[TrackerSelection, TrackerInfo]
) -> None:
    """All four trackers require "WEB-DL".

    QualitySelection.WEB_DL was "WEBDL", and that value goes straight into the
    title -- both when the source is detected and when the wizard's Quality
    combo supplies it as an override, since the combo's item text *is* the
    enum value.
    """
    rendered = _render(packaged[tracker], ENCODE_NAME, "WEB-DL")

    assert " WEB-DL " in rendered
    assert "WEBDL" not in rendered


@pytest.mark.parametrize("tracker", ALL_FOUR)
def test_a_legacy_webdl_override_is_canonicalized(
    tracker: TrackerSelection, packaged: dict[TrackerSelection, TrackerInfo]
) -> None:
    """A job saved before the rename replays "WEBDL" from its stored
    dynamic_data, and must still render the current spelling."""
    rendered = _render(packaged[tracker], ENCODE_NAME, "WEBDL")

    assert " WEB-DL " in rendered
    assert "WEBDL" not in rendered


@pytest.mark.parametrize("tracker", ALL_FOUR)
def test_repack_survives_into_the_tracker_title(
    tracker: TrackerSelection, packaged: dict[TrackerSelection, TrackerInfo]
) -> None:
    """Aither and LST both require REPACK in the title.

    `{re_release}` is gated on parse_filename_attributes, which
    generate_tracker_title never used to pass -- so the token sat in the
    packaged template resolving to nothing on every upload.
    """
    assert "REPACK" in _render(packaged[tracker], REMUX_NAME, "UHD BluRay")


@pytest.mark.parametrize("tracker", ALL_FOUR)
def test_a_remux_keeps_the_container_codec_name(
    tracker: TrackerSelection, packaged: dict[TrackerSelection, TrackerInfo]
) -> None:
    """A remux is HEVC/AVC; only an encode is x265/x264. Remux detection used
    to read the override alone, so a remux with no override was named as an
    encode."""
    rendered = _render(packaged[tracker], REMUX_NAME, "UHD BluRay")

    assert "HEVC" in rendered
    assert "x265" not in rendered


def test_beyondhd_tags_an_untagged_release_nogroup(
    packaged: dict[TrackerSelection, TrackerInfo],
) -> None:
    """BeyondHD rule 3.3.9, which names the exact spelling."""
    rendered = _render(
        packaged[TrackerSelection.BEYOND_HD], ENCODE_NAME, "BluRay", release_group=""
    )

    assert rendered.endswith("-NOGROUP")
    for wrong in ("NoGroup", "NOGRP", "NOTAG"):
        assert wrong not in rendered


@pytest.mark.parametrize(
    "tracker",
    (TrackerSelection.AITHER, TrackerSelection.LST, TrackerSelection.REELFLIX),
)
def test_the_other_three_leave_an_untagged_release_bare(
    tracker: TrackerSelection, packaged: dict[TrackerSelection, TrackerInfo]
) -> None:
    """ReelFliX 4.1 prefers a blank tag to a placeholder, and neither Aither
    nor LST asks for one. The separator has to go with it."""
    rendered = _render(packaged[tracker], ENCODE_NAME, "BluRay", release_group="")

    assert not rendered.endswith("-")
    assert "NOGROUP" not in rendered


@pytest.mark.parametrize("tracker", AUDIO_LAST)
def test_series_titles_carry_the_same_ordering_rule(
    tracker: TrackerSelection, packaged: dict[TrackerSelection, TrackerInfo]
) -> None:
    """Aither's and LST's season templates split on release type exactly as
    their film templates do, so an episode must not be ordered one way and a
    movie another."""
    info = packaged[tracker]
    for episode_format in SUPPORTED_TVR_FORMATS:
        entry = (info.tvr_title_overrides or {})[episode_format]
        remux = _render(
            info,
            REMUX_NAME,
            "UHD BluRay",
            token=entry.token,
            colon_replace=entry.colon_replace,
            replace_map=entry.replace_map,
            season_number=1,
            episode_number=2,
        )
        encode = _render(
            info,
            ENCODE_NAME,
            "BluRay",
            token=entry.token,
            colon_replace=entry.colon_replace,
            replace_map=entry.replace_map,
            season_number=1,
            episode_number=2,
        )

        assert remux.endswith("HEVC TrueHD 7.1 Atmos-SomeGroup"), (
            f"{tracker} {episode_format} remux: {remux}"
        )
        assert encode.endswith("TrueHD 7.1 Atmos DV HDR x265-SomeGroup"), (
            f"{tracker} {episode_format} encode: {encode}"
        )


def test_lst_series_titles_carry_no_episode_title(
    packaged: dict[TrackerSelection, TrackerInfo],
) -> None:
    """LST's series template has no episode-title slot and none of its
    examples use one ("The Agency 2024 S01E10 2160p PMTP WEB-DL DD+ 5.1 DV
    HDR10+ H.265-NTb"). Aither's examples do, so the two differ on purpose."""
    lst = packaged[TrackerSelection.LST].tvr_title_overrides or {}
    aither = packaged[TrackerSelection.AITHER].tvr_title_overrides or {}

    for episode_format in SUPPORTED_TVR_FORMATS:
        assert "episode_title" not in lst[episode_format].token
        assert "episode_title_exact" in aither[episode_format].token


@pytest.mark.parametrize("tracker", ALL_FOUR)
def test_a_web_release_carries_its_streaming_service(
    tracker: TrackerSelection, packaged: dict[TrackerSelection, TrackerInfo]
) -> None:
    """Aither's WEB-DL template is "Resolution Service WEB-DL ...", and LST
    lists the service as the *source* for WEB-DLs and WEBRips -- so on both,
    the abbreviation sits immediately before WEB-DL."""
    rendered = _render(packaged[tracker], WEB_NAME, "WEB-DL")

    assert " AMZN WEB-DL " in rendered


@pytest.mark.parametrize("tracker", ALL_FOUR)
def test_a_non_web_release_carries_no_streaming_service(
    tracker: TrackerSelection, packaged: dict[TrackerSelection, TrackerInfo]
) -> None:
    """Aither scopes the component to "Web content only". A disc or an encode
    never came from a service, and the AMZN in a filename must not survive a
    source change into a BluRay title."""
    rendered = _render(packaged[tracker], WEB_NAME, "BluRay")

    assert "AMZN" not in rendered
    assert rendered == (
        "Movie Name 2026 2160p BluRay TrueHD 7.1 Atmos DV HDR x265-SomeGroup"
    )


@pytest.mark.parametrize("tracker", ALL_FOUR)
def test_an_explicit_service_choice_is_honoured(
    tracker: TrackerSelection, packaged: dict[TrackerSelection, TrackerInfo]
) -> None:
    """The rename page's Service combo has to win over detection -- that is
    the whole point of offering it."""
    rendered = _render(packaged[tracker], WEB_NAME, "WEB-DL", streaming_service="PMTP")

    assert " PMTP WEB-DL " in rendered
    assert "AMZN" not in rendered
