"""The hardcoded entries must match the naming rules each tracker publishes.

`test_title_rules.py` and `test_title_render.py` check the machinery: that
an entry is well formed and that composing and normalising one behaves. This
file checks that what the entries *say* is right -- the exact component
order, spelling and separators from each tracker's own wiki -- by rendering
through the real pipeline and reading the finished string.

The rules being pinned, quoted as saved:

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
- ReelFliX ........ the same remux/encode split as Aither and LST, video
                    ahead of audio on a remux; blank tag preferred over a
                    NOGROUP placeholder
- BeyondHD ........ remux/encode/web-dl with no tag must end "-NOGROUP"

Known gaps, deliberately not asserted because NfoForge has no token for them.
Each needs a new token rather than an edit to an entry:

- Full discs. Aither's Country and LST's Region, plus their disc-specific
  source spellings ("Blu-ray", "NTSC DVD9", "3xDVD9") where `{source}` renders
  "BluRay"/"DVD". Full-disc uploads are not supported yet, so this stays out.
- Spoken-language components: FRENCH/JAPANESE and ZXX. Dual-Audio and Dubbed
  are *not* gaps -- `{audio_language_dual}` and `{localization}` cover them,
  and the Dub component composes the pair on Aither, LST and ReelFliX.
- LST-only: Hi10P, 3D and RERip. "PQ10" is no longer a gap either: the
  dynamic range resolves to an identity and each entry spells it, so LST and
  ReelFliX say "PQ10" where Aither says nothing at all.
- `{cut}` renders "Directors Cut" and "Extended Cut" where both trackers want
  "Director's Cut" and "Extended". The normalization table behind it is shared
  with filename generation, where an apostrophe is unwanted, so this cannot be
  fixed for titles alone.
"""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken
from src.backend.trackers.title_render import (
    compose_token_string,
    normalise_title,
    render_tracker_title,
)
from src.backend.trackers.title_rules import TITLE_RULES, ReleaseProperties
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.backend.utils.filename_claims import detect_filename_claims
from src.backend.utils.hdr_identity import resolve_hdr_identity
from src.config.models import ClaimSwitches
from src.config.tv_tokens import SUPPORTED_TVR_FORMATS
from src.enums.media_type import MediaType
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
from src.enums.tracker_selection import TrackerSelection
from src.payloads.media_search import MediaSearchPayload

# The release shapes the rules distinguish. Only the *name* matters here: it
# drives the filename attributes (REMUX/HYBRID/REPACK) and the source guess,
# while the mediainfo behind it stays the example payload's.
REMUX_NAME = "Movie.Name.2026.REPACK.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.REMUX-SomeGroup.mkv"
ENCODE_NAME = "Movie.Name.2026.1080p.BluRay.TrueHD.Atmos.7.1.DV.HEVC.x265-SomeGroup.mkv"
WEB_NAME = (
    "Movie.Name.2026.2160p.AMZN.WEB-DL.TrueHD.Atmos.7.1.DV.HEVC.H.265-SomeGroup.mkv"
)


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


_CLAIM_KEYS = ("edition", "frame_size", "localization", "re_release", "remux", "hybrid")


def _claim_overrides(name: str) -> dict[str, str]:
    """The six switchable claims stage 1 reads from a release name."""
    detected = detect_filename_claims(
        [Path(name).stem],
        ClaimSwitches(
            enabled=True,
            edition=True,
            frame_size=True,
            localization=True,
            re_release=True,
            remux=True,
            hybrid=True,
        ),
    ).as_override_tokens()
    return {k: v for k, v in detected.items() if k in _CLAIM_KEYS}


SERIES_TITLE = "Show Name"
EPISODE_TITLE = "Some Episode Title"


def _series_payloads(
    media, season: int, episodes: tuple[int, ...], episode_name: str
) -> tuple[object, MediaSearchPayload]:
    """Turn the example payload into one of the three series shapes.

    A season pack maps no episode at all, which is how the app represents
    one. A span carries `episode_end`, which is the only definition of a
    span in the token replacer -- so a test cannot accidentally build a
    span that the tokens would not recognise as one.
    """
    path = media.input_path
    episode_map: dict[Path, dict[str, object]] = {}
    if episodes:
        row: dict[str, object] = {
            "season": season,
            "episode": episodes[0],
            "episode_name": episode_name,
            "episode_data": {
                "seasonNumber": season,
                "number": episodes[0],
                "name": episode_name,
            },
        }
        if len(episodes) > 1:
            row["episode_end"] = episodes[-1]
        episode_map[path] = row

    series_media = replace(
        media, media_type=MediaType.SERIES, series_episode_map=episode_map
    )
    search = MediaSearchPayload(
        media_type=MediaType.SERIES,
        title=SERIES_TITLE,
        tvdb_data={
            "episodes": [
                {"seasonNumber": season, "number": number, "name": episode_name}
                for number in episodes
            ]
        },
    )
    return series_media, search


def _render(
    tracker: TrackerSelection,
    name: str,
    source: str,
    *,
    release_group: str | None = None,
    streaming_service: str | None = None,
    season: int | None = None,
    episodes: tuple[int, ...] = (),
    episode_name: str = EPISODE_TITLE,
) -> str:
    """Render a tracker's title exactly as generate_tracker_title would.

    Goes through the real pipeline -- compose from the entry, render, then
    normalise -- rather than reaching for a packaged token string, which no
    longer exists.

    Passing a season switches the payload to a series one, so the episode
    tokens are asked the same question the app asks them.
    """
    # Stage 3 no longer reads the six switchable claims off the filename, so
    # they arrive as overrides -- exactly what generate_tracker_title
    # receives from the rename page. Streaming service and release group are
    # deliberately not injected unless a test asks: those are still detected
    # downstream, and an override would bypass the service token's own
    # web-source gating.
    overrides: dict[str, str] = _claim_overrides(name)
    overrides["source"] = source
    if release_group is not None:
        overrides["release_group"] = release_group
    if streaming_service is not None:
        overrides["streaming_service"] = streaming_service

    media = _media(name)
    search = EXAMPLE_SEARCH_PAYLOAD
    if season is not None:
        media, search = _series_payloads(media, season, episodes, episode_name)
    media_info = next(iter(media.file_list_mediainfo.values()), None)
    height = 0
    if media_info and media_info.video_tracks:
        raw_height = media_info.video_tracks[0].height
        height = int(raw_height) if raw_height else 0

    release = ReleaseProperties(
        is_remux=bool(overrides.get("remux")),
        is_dvd="dvd" in source.lower(),
        resolution=height,
        hdr_identity=resolve_hdr_identity(media_info),
        season=season,
        episodes=episodes,
    )

    def render(token_string: str) -> str | None:
        return TokenReplacer(
            media_input_obj=media,
            media_search_obj=search,
            token_string=token_string,
            colon_replace=ColonReplace.KEEP,
            flatten=True,
            file_name_mode=False,
            token_type=FileToken,
            unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
            override_tokens=overrides,
            season_number=season,
            episode_number=episodes[0] if episodes else None,
        ).get_output()

    output = render_tracker_title(
        tracker,
        release,
        render=render,
        global_template="",
        global_colon=ColonReplace.KEEP,
    )
    assert output is not None
    return output


AUDIO_LAST = (TrackerSelection.AITHER, TrackerSelection.LST)


@pytest.mark.parametrize("tracker", AUDIO_LAST)
def test_remux_puts_hdr_and_video_codec_before_the_audio(
    tracker: TrackerSelection,
) -> None:
    """Aither: "Source REMUX HDR VideoCodec AudioCodec Channels Metadata".

    Compare Aither's own example, "X-Men: Days of Future Past 2014 2160p UHD
    BluRay REMUX HDR HEVC DTS-HD MA 7.1-FraMeSToR", and LST's, "The Lord of
    the Rings: The Two Towers 2002 2160p UHD BluRay REMUX DV HDR HEVC TrueHD
    7.1 Atmos-FraMeSToR".
    """
    rendered = _render(tracker, REMUX_NAME, "UHD BluRay")

    assert rendered == (
        "Movie Name 2026 REPACK 2160p UHD BluRay REMUX DV HDR HEVC "
        "TrueHD 7.1 Atmos-SomeGroup"
    )


@pytest.mark.parametrize("tracker", AUDIO_LAST)
def test_encode_puts_the_audio_before_hdr_and_video_codec(
    tracker: TrackerSelection,
) -> None:
    """The other half of the split: "Source AudioCodec Channels Metadata HDR
    VideoCodec", as in Aither's "Halo S01 2160p UHD BluRay TrueHD 7.1 Atmos DV
    HDR x265-Stelks"."""
    rendered = _render(tracker, ENCODE_NAME, "BluRay")

    assert rendered == (
        "Movie Name 2026 2160p BluRay TrueHD 7.1 Atmos DV HDR x265-SomeGroup"
    )


def test_lst_formats_eac3_atmos_as_codec_channels_atmos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin LST's documented order and its DDP -> DD+ spelling together.

    A test using TrueHD alone would not exercise LST's character-map rule,
    whose lookahead only matches when the channel layout immediately follows
    the codec.
    """
    media = deepcopy(_media(WEB_NAME))
    audio = next(iter(media.file_list_mediainfo.values())).audio_tracks[0]
    audio.channel_s = 6
    audio.other_channel_s = ["6 channels"]
    audio.channel_positions = "L R C LFE Ls Rs"
    monkeypatch.setattr(
        "src.backend.token_replacer.AudioCodecs.get_codec",
        lambda *_args: "DDP Atmos",
    )
    composition = TITLE_RULES[TrackerSelection.LST].composition
    normalisation = TITLE_RULES[TrackerSelection.LST].normalisation
    assert composition is not None

    overrides = {**_claim_overrides(WEB_NAME), "source": "WEB-DL"}
    release = ReleaseProperties(resolution=2160, hdr_identity="DV HDR10")
    rendered = TokenReplacer(
        media_input_obj=media,
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        token_string=compose_token_string(composition, release),
        colon_replace=ColonReplace.KEEP,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        override_tokens=overrides,
    ).get_output()

    assert rendered is not None
    normalised = normalise_title(
        rendered, normalisation, global_colon=ColonReplace.KEEP
    )
    assert "DD+ 5.1 Atmos" in normalised
    assert "DD+ Atmos 5.1" not in normalised


ALL_FOUR = (
    TrackerSelection.AITHER,
    TrackerSelection.LST,
    TrackerSelection.REELFLIX,
    TrackerSelection.BEYOND_HD,
)


@pytest.mark.parametrize("tracker", ALL_FOUR)
def test_web_releases_are_spelled_web_dl(tracker: TrackerSelection) -> None:
    """All four trackers require "WEB-DL".

    QualitySelection.WEB_DL was "WEBDL", and that value goes straight into the
    title -- both when the source is detected and when the wizard's Quality
    combo supplies it as an override, since the combo's item text *is* the
    enum value.
    """
    rendered = _render(tracker, ENCODE_NAME, "WEB-DL")

    assert " WEB-DL " in rendered
    assert "WEBDL" not in rendered


@pytest.mark.parametrize("tracker", ALL_FOUR)
def test_a_legacy_webdl_override_is_canonicalized(tracker: TrackerSelection) -> None:
    """A job saved before the rename replays "WEBDL" from its stored
    dynamic_data, and must still render the current spelling."""
    rendered = _render(tracker, ENCODE_NAME, "WEBDL")

    assert " WEB-DL " in rendered
    assert "WEBDL" not in rendered


@pytest.mark.parametrize("tracker", ALL_FOUR)
def test_repack_survives_into_the_tracker_title(tracker: TrackerSelection) -> None:
    """Aither and LST both require REPACK in the title.

    `{re_release}` is gated on parse_filename_attributes, which
    generate_tracker_title never used to pass -- so the token sat in the
    packaged template resolving to nothing on every upload.
    """
    assert "REPACK" in _render(tracker, REMUX_NAME, "UHD BluRay")


@pytest.mark.parametrize("tracker", ALL_FOUR)
def test_a_remux_keeps_the_container_codec_name(tracker: TrackerSelection) -> None:
    """A remux is HEVC/AVC; only an encode is x265/x264. Remux detection used
    to read the override alone, so a remux with no override was named as an
    encode."""
    rendered = _render(tracker, REMUX_NAME, "UHD BluRay")

    assert "HEVC" in rendered
    assert "x265" not in rendered


@pytest.mark.parametrize("tracker", (TrackerSelection.BEYOND_HD, TrackerSelection.LST))
def test_beyondhd_and_lst_tag_an_untagged_release_nogroup(
    tracker: TrackerSelection,
) -> None:
    """BeyondHD's rules name the exact spelling, and LST's own
    published example ends "x264-NOGROUP"."""
    rendered = _render(tracker, ENCODE_NAME, "BluRay", release_group="")

    assert rendered.endswith("-NOGROUP")
    for wrong in ("NoGroup", "NOGRP", "NOTAG"):
        assert wrong not in rendered


@pytest.mark.parametrize(
    "tracker",
    (TrackerSelection.AITHER, TrackerSelection.REELFLIX),
)
def test_aither_and_reelflix_leave_an_untagged_release_bare(
    tracker: TrackerSelection,
) -> None:
    """ReelFliX prefers a blank tag to a placeholder, and Aither asks
    for none either. The separator has to go with it.

    LST was on this list and does not belong: its own published example is
    "Transformers 2007 DVDRip DD 5.1 x264-NOGROUP". It is asserted with
    BeyondHD below.
    """
    rendered = _render(tracker, ENCODE_NAME, "BluRay", release_group="")

    assert not rendered.endswith("-")
    assert "NOGROUP" not in rendered


@pytest.mark.parametrize("tracker", AUDIO_LAST)
def test_series_titles_carry_the_same_ordering_rule(tracker: TrackerSelection) -> None:
    """An episode must not be ordered one way and a film another.

    One entry serves both media types, so this is now a statement about
    the same composition rather than about two templates agreeing.
    """
    remux = _render(tracker, REMUX_NAME, "UHD BluRay", season=1, episodes=(2,))
    encode = _render(tracker, ENCODE_NAME, "BluRay", season=1, episodes=(2,))

    assert remux.index("{}".format("HEVC")) < remux.index("TrueHD")
    assert encode.index("TrueHD") < encode.index("x265")


def test_lst_series_titles_carry_no_episode_title() -> None:
    """LST's series template has no episode-title slot and none of its
    examples use one ("The Agency 2024 S01E10 2160p PMTP WEB-DL DD+ 5.1 DV
    HDR10+ H.265-NTb"). Aither's examples do, so the two differ on purpose."""
    lst = TITLE_RULES[TrackerSelection.LST].composition
    aither = TITLE_RULES[TrackerSelection.AITHER].composition
    assert lst is not None
    assert aither is not None

    assert "{episode_title_exact}" not in lst.components
    assert "{episode_title_exact}" in aither.components


# The three shapes a series release comes in, and the designator each gets.
# A season pack maps no episode; a span maps a range.
SINGLE_EPISODE = (1, (2,))
SEASON_PACK = (1, ())
EPISODE_SPAN = (1, (1, 2, 3))


@pytest.mark.parametrize(
    ("season", "episodes", "expected"),
    [
        (*SINGLE_EPISODE, f"Show Name S01E02 {EPISODE_TITLE} 2160p BluRay"),
        (*SEASON_PACK, "Show Name S01 2160p BluRay"),
        (*EPISODE_SPAN, "Show Name S01E01-03 2160p BluRay"),
    ],
    ids=["single episode", "season pack", "episode span"],
)
def test_aither_carries_an_episode_title_for_a_single_episode_only(
    season: int, episodes: tuple[int, ...], expected: str
) -> None:
    """Aither's examples name the episode, and only one episode has a name.

    A season pack has no episode to name. A span has several, so naming it
    after the first would assert that one episode's title describes all of
    them. Neither suppression lives in Aither's entry -- the entry carries
    `{episode_title_exact}` unconditionally and no omit rule mentions it --
    so both come from the token, which every tracker shares.
    """
    composition = TITLE_RULES[TrackerSelection.AITHER].composition
    assert composition is not None
    assert "{episode_title_exact}" in composition.components
    for rule in composition.omit:
        assert "{episode_title_exact}" not in rule.components

    rendered = _render(
        TrackerSelection.AITHER, ENCODE_NAME, "BluRay", season=season, episodes=episodes
    )

    assert rendered.startswith(expected)
    assert rendered.endswith("TrueHD 7.1 Atmos DV HDR x265-SomeGroup")


@pytest.mark.parametrize(
    ("season", "episodes", "designator"),
    [
        (*SINGLE_EPISODE, "S01E02"),
        (*SEASON_PACK, "S01"),
        (*EPISODE_SPAN, "S01E01-03"),
    ],
    ids=["single episode", "season pack", "episode span"],
)
def test_lst_carries_no_episode_title_in_any_shape(
    season: int, episodes: tuple[int, ...], designator: str
) -> None:
    """LST is unaffected across all three, which is the control.

    Had the span suppression been written into Aither's entry instead of the
    shared token, LST would read identically here for the wrong reason -- so
    this is asserted alongside the entry check in the Aither test above,
    which is what tells the two apart.
    """
    rendered = _render(
        TrackerSelection.LST, ENCODE_NAME, "BluRay", season=season, episodes=episodes
    )

    assert rendered == (
        f"Show Name {designator} 2160p BluRay TrueHD 7.1 Atmos DV HDR x265-SomeGroup"
    )
    assert EPISODE_TITLE not in rendered


@pytest.mark.parametrize(
    "tracker",
    (
        TrackerSelection.DARK_PEERS,
        TrackerSelection.SHARE_ISLAND,
        TrackerSelection.UPLOAD_CX,
        TrackerSelection.ONLY_ENCODES,
    ),
)
@pytest.mark.parametrize(
    ("season", "episodes", "designator", "names_the_episode"),
    [
        (*SINGLE_EPISODE, "S01E02", True),
        (*SEASON_PACK, "S01", False),
        (*EPISODE_SPAN, "S01E01-03", False),
    ],
    ids=["single episode", "season pack", "episode span"],
)
def test_a_transcribed_entry_serves_series_as_well_as_film(
    tracker: TrackerSelection,
    season: int,
    episodes: tuple[int, ...],
    designator: str,
    names_the_episode: bool,
) -> None:
    """These four were transcribed from a film-only shipped override.

    An entry has no media-type split, so its composition governs their
    series titles too, where the user's global template used to. The config
    said nothing about series, so the shape follows every other tracker
    here: name the episode where there is one episode to name, and let the
    shared token suppress it for a pack or a span.
    """
    rendered = _render(tracker, ENCODE_NAME, "BluRay", season=season, episodes=episodes)

    assert f"Show Name {designator} " in rendered
    assert (EPISODE_TITLE in rendered) is names_the_episode
    # {release_year} is omitted for a series, so the year must not survive
    assert "2026" not in rendered
    assert "  " not in rendered
    assert not rendered.endswith(("-", ".", "_"))
    assert rendered.endswith("-SomeGroup")


def test_lst_bands_a_double_episode_and_ranges_a_longer_span() -> None:
    """LST's rule is `S##E##E##` at exactly two and `S##E##-##` above.

    No single `multi_episode_style` produces both, which is why the
    designator is a composition field rather than that user setting. Aither
    ranges at two, so the same release is designated differently per
    tracker.
    """
    double = _render(
        TrackerSelection.LST, ENCODE_NAME, "BluRay", season=1, episodes=(1, 2)
    )
    many = _render(
        TrackerSelection.LST, ENCODE_NAME, "BluRay", season=1, episodes=(1, 2, 3)
    )
    aither_double = _render(
        TrackerSelection.AITHER, ENCODE_NAME, "BluRay", season=1, episodes=(1, 2)
    )

    assert "Show Name S01E01E02 " in double
    assert "Show Name S01E01-03 " in many
    assert "Show Name S01E01-02 " in aither_double


@pytest.mark.parametrize(
    "punctuated", ["Who Are You?", "Chapter 1: The Beginning", "Face/Off"]
)
def test_aither_renders_a_film_and_an_episode_title_identically(
    punctuated: str,
) -> None:
    """Aither is the only entry carrying {episode_title_exact}.

    Its film template carries {title_exact}, which applies no formatting, so
    a punctuated film title reaches the tracker as typed. The episode token
    used to strip `[:\\/<>?*"|]` first, which meant the two halves of one
    tracker's entry disagreed about the same string -- and, for the colon,
    disagreed with Aither's own colon_replace setting, which is KEEP.
    """
    path = Path(ENCODE_NAME)
    # One payload carrying the same string as the series name and as the
    # episode name, so {title_exact} and {episode_title_exact} are asked the
    # same question.
    media_input = replace(
        EXAMPLE_MEDIA_INPUT_PAYLOAD,
        input_path=path,
        file_list=[path],
        media_type=MediaType.SERIES,
        series_episode_map={
            path: {
                "season": 1,
                "episode": 2,
                "episode_name": punctuated,
                "episode_data": {
                    "seasonNumber": 1,
                    "number": 2,
                    "name": punctuated,
                },
            }
        },
    )
    search = MediaSearchPayload(
        media_type=MediaType.SERIES,
        title=punctuated,
        tvdb_data={"episodes": [{"seasonNumber": 1, "number": 2, "name": punctuated}]},
    )

    normalisation = TITLE_RULES[TrackerSelection.AITHER].normalisation
    assert normalisation.colon is not None
    for episode_format in SUPPORTED_TVR_FORMATS:
        rendered = TokenReplacer(
            media_input_obj=media_input,
            media_search_obj=search,
            token_string="{title_exact}|{episode_title_exact}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
            colon_replace=normalisation.colon,
            flatten=True,
            file_name_mode=False,
            token_type=FileToken,
            unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
            season_number=1,
            episode_number=2,
        ).get_output()

        assert rendered is not None
        film, episode = rendered.split("|")
        assert episode == film == punctuated, (
            f"{episode_format}: film={film!r} episode={episode!r}"
        )


@pytest.mark.parametrize("tracker", ALL_FOUR)
def test_a_web_release_carries_its_streaming_service(tracker: TrackerSelection) -> None:
    """Aither's WEB-DL template is "Resolution Service WEB-DL ...", and LST
    lists the service as the *source* for WEB-DLs and WEBRips -- so on both,
    the abbreviation sits immediately before WEB-DL."""
    rendered = _render(tracker, WEB_NAME, "WEB-DL")

    assert " AMZN WEB-DL " in rendered


@pytest.mark.parametrize("tracker", ALL_FOUR)
def test_a_non_web_release_carries_no_streaming_service(
    tracker: TrackerSelection,
) -> None:
    """Aither scopes the component to "Web content only". A disc or an encode
    never came from a service, and the AMZN in a filename must not survive a
    source change into a BluRay title."""
    rendered = _render(tracker, WEB_NAME, "BluRay")

    # BeyondHD puts Atmos with the codec and the channels after it,
    # where the other three spell it the other way round.
    audio = (
        "TrueHD Atmos 7.1"
        if tracker is TrackerSelection.BEYOND_HD
        else "TrueHD 7.1 Atmos"
    )

    assert "AMZN" not in rendered
    assert rendered == (f"Movie Name 2026 2160p BluRay {audio} DV HDR x265-SomeGroup")


@pytest.mark.parametrize("tracker", ALL_FOUR)
def test_an_explicit_service_choice_is_honoured(tracker: TrackerSelection) -> None:
    """The rename page's Service combo has to win over detection -- that is
    the whole point of offering it."""
    rendered = _render(tracker, WEB_NAME, "WEB-DL", streaming_service="PMTP")

    assert " PMTP WEB-DL " in rendered
    assert "AMZN" not in rendered
