"""Regression coverage for audio channel layouts in tracker release titles.

Every tracker that ships a space-separated title converts the dot-separated
form by replacing periods with spaces -- which destroys the audio channel
layout (``5.1`` -> ``5 1``) along with the separators. UNIT3D used to put the
periods back with a lookup table built from 11 hard-coded codecs x 11
hard-coded layouts, so the layout only survived when it was immediately
preceded by one of those exact codec strings. Everything outside that grid
silently uploaded as ``5 1`` / ``2 0``:

* codecs the table never listed -- AAC, Opus, LPCM, MP2, MP3, Vorbis,
  ``DTS 96-24``, and ``DTS-X`` (the table held ``DTS:X``, which the audio
  conventions never emit),
* an Atmos suffix sitting between the codec and the channels, which every
  tracker using a ``{audio_codec} {audio_channel_s}`` title token produces,
* the layouts ``6.0``, ``7.0`` and ``8.0``, which the table simply omitted.

TorrentLeech and HDBits had no restore step at all and lost every layout.
``strip_title_dots`` now protects the layout by shape before the periods are
stripped, so these tests lock in the full codec x layout grid.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken
from src.backend.trackers.title_render import normalise_title
from src.backend.trackers.title_rules import TITLE_RULES
from src.backend.trackers.utils import strip_title_dots
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.config.config import ConfigManager
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
from src.enums.tracker_selection import TrackerSelection
from tests.test_config.config_tree import build_config_paths

# every codec runtime/config/audio_conventions/default.json can emit
CODECS = (
    "AAC",
    "DD",
    "DD-EX",
    "DD+",
    "DDP",
    "DDP Atmos",
    "TrueHD",
    "TrueHD Atmos",
    "DTS",
    "DTS-ES",
    "DTS-HD MA",
    "DTS-HD HRA",
    "DTS-X",
    "DTS 96-24",
    "FLAC",
    "MP2",
    "MP3",
    "Opus",
    "LPCM",
    "Vorbis",
)

# every layout ParseAudioChannels.get_channel_layout can produce (AudioChannels
# allows 1-8 channels, minus one when LFE is present), plus an Atmos-style
# height group
LAYOUTS = (
    "1.0",
    "2.0",
    "2.1",
    "3.0",
    "3.1",
    "4.0",
    "4.1",
    "5.0",
    "5.1",
    "6.0",
    "6.1",
    "7.0",
    "7.1",
    "8.0",
    "8.1",
    "7.1.4",
)


def _normaliser(tracker: TrackerSelection) -> Callable[[str], str]:
    """One tracker's normalisation, as a plain string transform.

    The uploaders each had their own formatter when this file was written;
    all of it is an entry's normalisation now. The three below still cover
    what they covered: a plain spaced entry, one that logs a correction,
    and the most heavily normalised tracker in the codebase.
    """
    normalisation = TITLE_RULES[tracker].normalisation

    def normalise(title: str) -> str:
        return normalise_title(title, normalisation, global_colon=ColonReplace.KEEP)

    return normalise


GENERATORS: tuple[Callable[[str], str], ...] = (
    _normaliser(TrackerSelection.BLUTOPIA),
    _normaliser(TrackerSelection.TORRENT_LEECH),
    _normaliser(TrackerSelection.HDB),
)
_SEEDPOOL = _normaliser(TrackerSelection.SEEDPOOL)


@pytest.mark.parametrize("codec", CODECS)
@pytest.mark.parametrize("layout", LAYOUTS)
def test_a_spaced_entry_keeps_every_codec_and_layout(codec: str, layout: str) -> None:
    title = f"Example Movie 2026 1080p BluRay {codec} {layout} AVC-GRP"

    assert f"{codec} {layout} " in _normaliser(TrackerSelection.BLUTOPIA)(title)


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("generate", GENERATORS)
def test_every_tracker_keeps_layout_from_a_dotted_filename(
    generate: Callable[[str], str], layout: str
) -> None:
    stem = f"Example.Movie.2026.1080p.BluRay.AAC.{layout}.x264-GRP"

    assert f"AAC {layout} " in generate(stem)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # separator periods still become spaces
        (
            "Example.Movie.2026.1080p.BluRay.DTS-HD.MA.5.1.x264-GRP",
            "Example Movie 2026 1080p BluRay DTS-HD MA 5.1 x264-GRP",
        ),
        # a year/resolution boundary is not a layout
        (
            "Example.Movie.2019.1080p.WEB-DL.DDP.2.0.H.264-GRP",
            "Example Movie 2019 1080p WEB-DL DDP 2.0 H.264-GRP",
        ),
        # an Atmos suffix between codec and channels was the common failure
        (
            "Example Movie 2026 1080p WEB-DL DDP Atmos 5.1 H.264-GRP",
            "Example Movie 2026 1080p WEB-DL DDP Atmos 5.1 H.264-GRP",
        ),
        # a bare part number followed by a resolution is not a layout
        (
            "Example.Movie.Part.2.1080p.WEB-DL.AAC.2.0.x264-GRP",
            "Example Movie Part 2 1080p WEB-DL AAC 2.0 x264-GRP",
        ),
        # a real decimal is not a layout -- .5 is not an LFE digit
        (
            "Nine.9.5.Weeks.2026.1080p.BluRay.DDP.2.0.x264-GRP",
            "Nine 9 5 Weeks 2026 1080p BluRay DDP 2.0 x264-GRP",
        ),
        # hyphenated digits are untouched
        (
            "9-1-1 S01E01 Pilot 1080p WEB-DL AAC 2.0 H.264-GRP",
            "9-1-1 S01E01 Pilot 1080p WEB-DL AAC 2.0 H.264-GRP",
        ),
        # repeated whitespace is still collapsed
        ("Example  Movie   2026 1080p AAC 2.0", "Example Movie 2026 1080p AAC 2.0"),
    ],
)
def test_strip_title_dots(title: str, expected: str) -> None:
    assert strip_title_dots(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        "Example.Movie.2026.1080p.BluRay.DTS-HD.MA.5.1.x264-GRP",
        "Example Movie 2026 1080p WEB-DL DDP Atmos 5.1 H.264-GRP",
        "Example Movie 2026 2160p UHD BluRay TrueHD Atmos 7.1.4 HEVC-GRP",
    ],
)
@pytest.mark.parametrize("generate", GENERATORS)
def test_normalisation_is_idempotent(
    generate: Callable[[str], str], title: str
) -> None:
    once = generate(title)

    assert generate(once) == once


def _config_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConfigManager:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    return ConfigManager("test", build_config_paths(tmp_path))


def _apply_title_rules(title: str, rules: list[tuple[str, str]]) -> str | None:
    """Run a packaged replace_map the way generate_tracker_title runs it.

    The token string is a finished title with no tokens in it, so this
    exercises only the final title formatting -- which is where
    `override_title_rules` is applied.
    """
    return TokenReplacer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        token_string=title,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        override_title_rules=rules,
    ).get_output()


@pytest.mark.parametrize("layout", LAYOUTS)
def test_no_packaged_title_rule_destroys_a_layout(
    layout: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tracker formatters above are the last step, not the only one.

    A tracker's packaged `replace_map` runs earlier, at title generation, and
    is a plain regex substitution with none of `strip_title_dots`' layout
    protection. TorrentLeech shipped a bare escaped-dot-to-space rule, so its
    titles reached the safe formatter already reading "7 1" and there was
    nothing left to protect -- the fix in `strip_title_dots` could never have
    covered it.
    """
    manager = _config_manager(tmp_path, monkeypatch)
    title = f"Example Movie 2026 1080p BluRay TrueHD Atmos {layout} x264-GRP"

    for tracker, info in manager.defaults.trackers.by_selection().items():
        rule_sets: list[tuple[str, list[tuple[str, str]] | None]] = [
            ("movie", info.mvr_title_replace_map)
        ]
        rule_sets.extend(
            (str(fmt), entry.replace_map)
            for fmt, entry in (info.tvr_title_overrides or {}).items()
        )
        for label, rules in rule_sets:
            if not rules:
                continue
            output = _apply_title_rules(title, rules)
            assert output is not None
            assert f" {layout} " in output, (
                f"{tracker}'s packaged {label} replace_map turned "
                f"{layout} into something else: {output}"
            )


@pytest.mark.parametrize("codec", CODECS)
@pytest.mark.parametrize("layout", LAYOUTS)
def test_seedpool_keeps_every_codec_and_layout(codec: str, layout: str) -> None:
    """SeedPool converts the other way -- spaces to periods -- so a layout
    needs no protection to survive. Pinned across the same grid anyway, since
    the separator it emits is the one a layout is made of."""
    title = f"Example Movie 2026 1080p BluRay {codec} {layout} AVC-GRP"

    assert f".{layout}." in _SEEDPOOL(title)


@pytest.mark.parametrize(
    "title",
    [
        "Example Movie 2026 1080p BluRay DTS-HD MA 5.1 x264-GRP",
        "Example.Movie.2026.1080p.BluRay.DTS-HD.MA.5.1.x264-GRP",
        "Example  Movie   2026 1080p AAC 2.0",
    ],
)
def test_seedpool_release_title_is_idempotent(title: str) -> None:
    once = _SEEDPOOL(title)

    assert _SEEDPOOL(once) == once


# A video codec's internal period is the same casualty as a channel layout:
# `strip_title_dots` cannot tell it from a separator, so `H.264` shipped as
# `H 264` to every tracker that spaces its titles -- including LST, whose own
# published example spells it `H.264`.
VIDEO_CODECS_WITH_A_PERIOD = ("H.264", "H.265")


@pytest.mark.parametrize("codec", VIDEO_CODECS_WITH_A_PERIOD)
@pytest.mark.parametrize(
    "title_form",
    [
        "Example Movie 2026 1080p AMZN WEB-DL DD+ 5.1 Atmos {codec}-GRP",
        "Example.Movie.2026.1080p.AMZN.WEB-DL.DD+.5.1.Atmos.{codec}-GRP",
    ],
)
def test_strip_title_dots_keeps_a_video_codec_period(
    codec: str, title_form: str
) -> None:
    # Both forms matter: a composed title arrives space-separated, while the
    # release-name fallback arrives as a dotted filename stem.
    result = strip_title_dots(title_form.format(codec=codec))

    assert f" {codec}-GRP" in result, result


@pytest.mark.parametrize("codec", VIDEO_CODECS_WITH_A_PERIOD)
def test_a_video_codec_period_survives_every_spaced_tracker(codec: str) -> None:
    """LST publishes "... DD+ 5.1 Atmos H.264-GROUP" as a model name.

    Every tracker below routes through `strip_title_dots`, so all of them
    were emitting `H 264`. HDBits is excluded because it deliberately
    rewrites H.265 to HEVC; its H.264 case is covered above.
    """
    title = f"Example Movie 2026 1080p AMZN WEB-DL DD+ 5.1 Atmos {codec}-GRP"

    for name, normalise in (
        ("spaced", _normaliser(TrackerSelection.BLUTOPIA)),
        ("torrentleech", _normaliser(TrackerSelection.TORRENT_LEECH)),
    ):
        assert codec in normalise(title), name


def test_a_channel_layout_and_a_codec_period_survive_together() -> None:
    # The two protections must not undo each other -- they share a sentinel.
    result = strip_title_dots(
        "Example.Movie.2026.2160p.WEB-DL.TrueHD.7.1.4.Atmos.H.265-GRP"
    )

    assert result == "Example Movie 2026 2160p WEB-DL TrueHD 7.1.4 Atmos H.265-GRP"


@pytest.mark.parametrize(
    ("title", "expected_codec"),
    [
        ("Example Movie 2026 1080p AMZN WEB-DL DD+ 5.1 H.265-GRP", "HEVC"),
        ("Example Movie 2026 1080p AMZN WEB-DL DD+ 5.1 H 265-GRP", "HEVC"),
        ("Example Movie 2026 1080p AMZN WEB-DL DD+ 5.1 H265-GRP", "HEVC"),
        # HDBits takes H.264 as written; only the one codec is rewritten.
        ("Example Movie 2026 1080p AMZN WEB-DL DD+ 5.1 H.264-GRP", "H.264"),
    ],
)
def test_hdbits_rewrites_h265_but_not_h264(title: str, expected_codec: str) -> None:
    """HDBits is the one tracker that wants HEVC where NfoForge emits H.265.

    Its rewrite has to tolerate every separator, because the codec reaches it
    as `H.265` now that `strip_title_dots` preserves the period, as `H 265`
    from a title that was spaced before it arrived, and as `H265` from a
    hand-typed template -- HDBits has no composition, so a user's own global
    template is what it renders.
    """
    result = _normaliser(TrackerSelection.HDB)(title)

    assert result.endswith(f"{expected_codec}-GRP"), result
