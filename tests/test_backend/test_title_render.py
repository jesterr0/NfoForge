import re

import pytest

from src.backend.trackers.hdb import HDBUploader
from src.backend.trackers.title_render import compose_token_string, normalise_title
from src.backend.trackers.title_rules import (
    TITLE_RULES,
    Composition,
    ConditionalOrder,
    ConditionalRewrite,
    Designator,
    Normalisation,
    OmitRule,
    ReleaseProperties,
    Separator,
)
from src.enums.token_replacer import ColonReplace
from src.enums.tracker_selection import TrackerSelection


def _normalise(title: str, normalisation: Normalisation) -> str:
    return normalise_title(title, normalisation, global_colon=ColonReplace.KEEP)


def test_spaced_separator_strips_dots_but_keeps_layouts_and_codecs() -> None:
    result = _normalise(
        "Movie.2024.TrueHD.7.1.Atmos.H.265-GRP",
        Normalisation(separator=Separator.SPACED),
    )

    assert result == "Movie 2024 TrueHD 7.1 Atmos H.265-GRP"


def test_dotted_separator_keeps_the_release_form() -> None:
    result = _normalise(
        "Movie 2024 1080p WEB-DL H.264-GRP",
        Normalisation(separator=Separator.DOTTED),
    )

    assert result == "Movie.2024.1080p.WEB-DL.H.264-GRP"


def test_the_entry_colon_beats_the_users_global() -> None:
    # Field-level precedence: the entry's value wins where it has one.
    result = normalise_title(
        "Mission: Impossible 2024",
        Normalisation(colon=ColonReplace.KEEP),
        global_colon=ColonReplace.DELETE,
    )

    assert result == "Mission: Impossible 2024"


def test_the_users_global_colon_applies_when_the_entry_has_none() -> None:
    result = normalise_title(
        "Mission: Impossible 2024",
        Normalisation(colon=None),
        global_colon=ColonReplace.REPLACE_WITH_DASH,
    )

    assert result == "Mission- Impossible 2024"


def test_a_vocabulary_entry_rewrites_a_component() -> None:
    result = _normalise(
        "Movie 2024 DDP 5.1 x264-GRP",
        Normalisation(vocabulary={"DDP": "DD+"}),
    )

    assert result == "Movie 2024 DD+ 5.1 x264-GRP"


def test_a_vocabulary_entry_mapped_to_none_suppresses_it() -> None:
    # Aither suppresses PQ rather than spelling it.
    result = _normalise(
        "Movie 2024 2160p BluRay PQ x265-GRP",
        Normalisation(vocabulary={"PQ": None}),
    )

    assert result == "Movie 2024 2160p BluRay x265-GRP"


def test_vocabulary_matches_on_word_boundaries() -> None:
    """A map keyed on "DV" must not touch "DVDRip".

    A bare substring replace turns LST's own DVD example into "DoViDRip".
    """
    result = _normalise(
        "Transformers 2007 DVDRip DD 5.1 x264-GRP",
        Normalisation(vocabulary={"DV": "DoVi"}),
    )

    assert result == "Transformers 2007 DVDRip DD 5.1 x264-GRP"


def test_a_key_matches_where_the_group_tag_abuts_it() -> None:
    # The codec is the last component before the tag, so its trailing
    # boundary is a hyphen rather than a space.
    result = _normalise(
        "Movie 2024 1080p WEB-DL DD+ 5.1 H.265-GRP",
        Normalisation(vocabulary={"H.265": "HEVC"}),
    )

    assert result == "Movie 2024 1080p WEB-DL DD+ 5.1 HEVC-GRP"


def test_a_key_never_rewrites_the_release_group_itself() -> None:
    """The name after the final hyphen is a group, not a vocabulary term.

    A group named "DV" would otherwise be renamed to "DoVi" on any tracker
    mapping that value. hdb.py avoids this by bounding on whitespace; the
    shared rule bounds on a preceding hyphen, which also lets a key match
    where a tag abuts it on the *right*.
    """
    result = _normalise(
        "Movie 2024 1080p BluRay DD+ 5.1 x264-DV",
        Normalisation(vocabulary={"DV": "DoVi"}),
    )

    assert result == "Movie 2024 1080p BluRay DD+ 5.1 x264-DV"


def test_a_conditional_rewrite_fires_when_its_guard_is_absent() -> None:
    result = _normalise(
        "Movie 2024 2160p BluRay DV HDR HEVC-GRP",
        Normalisation(
            conditional_vocabulary=(
                ConditionalRewrite(
                    match="HDR", replacement="HDR10", unless_present="HDR10+"
                ),
            )
        ),
    )

    assert result == "Movie 2024 2160p BluRay DV HDR10 HEVC-GRP"


def test_a_conditional_rewrite_is_skipped_when_its_guard_is_present() -> None:
    # HDBits' rule: a bare HDR means HDR10, but not in a title that already
    # names HDR10+.
    result = _normalise(
        "Movie 2024 2160p BluRay HDR DV HDR10+ HEVC-GRP",
        Normalisation(
            conditional_vocabulary=(
                ConditionalRewrite(
                    match="HDR", replacement="HDR10", unless_present="HDR10+"
                ),
            )
        ),
    )

    assert result == "Movie 2024 2160p BluRay HDR DV HDR10+ HEVC-GRP"


def test_an_allowlist_strips_what_it_does_not_permit() -> None:
    result = _normalise(
        'Who Are You? 2024 <"*|> 1080p-GRP',
        Normalisation(allowlist=r"0-9a-zA-ZÀ-ÿ. :&+'\-\[\]"),
    )

    assert "?" not in result
    assert '"' not in result
    assert "Who Are You 2024" in result


def test_no_allowlist_keeps_punctuation() -> None:
    # Every tracker but HDBits publishes no character rule, and inventing
    # one would strip punctuation their own examples carry.
    result = _normalise("Who Are You? 2024 1080p-GRP", Normalisation())

    assert result == "Who Are You? 2024 1080p-GRP"


def test_an_allowlist_cleans_up_the_gap_it_leaves() -> None:
    """Stripping a character between a space and a period leaves " .".

    The allowlist permits the period, so nothing else removes it, and the
    separator pass has already run by this point.
    """
    result = _normalise(
        "Movie 2024 ?.5.1 x264-GRP",
        Normalisation(allowlist=r"0-9a-zA-ZÀ-ÿ. :&+'\-\[\]"),
    )

    assert " ." not in result
    assert ".." not in result


HDB_CORPUS = [
    "Movie Name 2024 2160p UHD BluRay REMUX DV HDR HEVC TrueHD 7.1 Atmos-GRP",
    "Movie.Name.2024.1080p.AMZN.WEB-DL.DD+.5.1.H.265-GRP",
    "Movie.Name.2024.1080p.AMZN.WEB-DL.DD+.5.1.H.264-GRP",
    "Show Name 2024 S01E10 2160p PMTP WEB-DL DD+ 5.1 DV HDR10+ H.265-GRP",
    "Transformers 2007 DVDRip DD 5.1 x264-GRP",
    'Who Are You? 2024 1080p BluRay <"*> DD 2.0 x264-GRP',
    "Movie Name 2024 1080p BluRay TrueHD 7.1.4 Atmos x265-GRP",
]


@pytest.mark.parametrize("title", HDB_CORPUS)
def test_the_hdbits_entry_reproduces_its_uploader(title: str) -> None:
    """The entry must be a faithful transcription, not an approximation.

    HDBits is the most heavily normalised tracker in the codebase, so it
    exercises every stage: separator, plain rewrites, a conditional
    rewrite, and an allowlist with its cleanup. While both implementations
    exist this can be asserted directly; once the uploader's own formatter
    goes, this test is what proves nothing was lost with it.

    Repeated whitespace is collapsed on both sides before comparing, so
    the rest of the comparison stays exact. That is the one place the two
    differ, and the entry is the correct one -- see the two tests below.
    """
    entry = TITLE_RULES[TrackerSelection.HDB].normalisation
    expected = re.sub(r"\s{2,}", " ", HDBUploader.generate_release_title(title))

    assert normalise_title(title, entry, global_colon=ColonReplace.KEEP) == expected


@pytest.mark.parametrize("tracker", list(TrackerSelection))
def test_no_entry_can_emit_a_gap(tracker: TrackerSelection) -> None:
    """No tracker wants two separators in a row, so no entry may emit them.

    A gap is not exotic: a vocabulary rule that suppresses a value leaves
    one, an allowlist that strips a token leaves one, and a component that
    does not resolve leaves one. Closing it belongs at the end of
    normalisation rather than in each rule that can open it.

    Asserted per separator, since the dotted entry's version of a gap is a
    repeated period rather than a repeated space.
    """
    entry = TITLE_RULES[tracker].normalisation
    gappy = 'Movie Name 2024  1080p BluRay <"*>  DD 2.0 x264-GRP'

    result = normalise_title(gappy, entry, global_colon=ColonReplace.KEEP)

    assert "  " not in result, result
    assert ".." not in result, result


def test_the_entry_closes_a_gap_the_hdbits_uploader_leaves_open() -> None:
    """The one place the entry and hdb.py differ, and why.

    hdb.py's cleanup handles the period case (`" ."`) but not the space
    case, so a title carrying a forbidden token has shipped to HDBits with
    a visible gap in it.
    """
    title = 'Who Are You? 2024 1080p BluRay <"*> DD 2.0 x264-GRP'
    entry = TITLE_RULES[TrackerSelection.HDB].normalisation

    assert "  " in HDBUploader.generate_release_title(title)
    assert "  " not in normalise_title(title, entry, global_colon=ColonReplace.KEEP)


# ---------------------------------------------------------------- composition


def _compose_body(composition: Composition, release: ReleaseProperties) -> str:
    """The composed token string without its trailing tag.

    Every composition ends with a release-group tag, which would otherwise
    have to be repeated in the expectation of every test that is not about
    tagging. The two that are assert the whole string.
    """
    return re.sub(
        r"\{:opt=-:release_group.*$", "", compose_token_string(composition, release)
    )


def _release(**overrides: object) -> ReleaseProperties:
    base: dict[str, object] = {
        "is_remux": False,
        "is_disc": False,
        "is_dvd": False,
        "resolution": 1080,
        "hdr_identity": "SDR",
        "season": None,
        "episodes": (),
    }
    base.update(overrides)
    return ReleaseProperties(**base)  # pyright: ignore[reportArgumentType]


def test_components_compose_in_the_entrys_order() -> None:
    composition = Composition(
        components=("{title_exact}", "{release_year}", "{resolution}")
    )

    assert _compose_body(composition, _release()) == (
        "{title_exact} {release_year} {resolution}"
    )


def test_a_conditional_order_swaps_on_remux() -> None:
    """LST, Aither and ReelFliX put video before audio on a remux.

    The shipped config said this by writing the same token twice at two
    positions, one guarded by only_if(remux) and the other by unless(remux).
    An entry says it once, in the place it applies.
    """
    composition = Composition(
        components=(
            "{source}",
            ConditionalOrder(
                when=lambda release: release.is_remux,
                then=("{video_codec}", "{audio_codec}"),
                otherwise=("{audio_codec}", "{video_codec}"),
            ),
            "{release_year}",
        )
    )

    remux = _compose_body(composition, _release(is_remux=True))
    encode = _compose_body(composition, _release(is_remux=False))

    assert remux == "{source} {video_codec} {audio_codec} {release_year}"
    assert encode == "{source} {audio_codec} {video_codec} {release_year}"


def test_a_conditional_block_keeps_its_position_in_the_order() -> None:
    # The swap happens mid-order, not at the end -- both trackers' published
    # forms share a prefix *and* a suffix around the part that moves.
    composition = Composition(
        components=(
            "{title_exact}",
            ConditionalOrder(
                when=lambda release: release.is_dvd,
                then=(),
                otherwise=("{resolution}",),
            ),
            "{source}",
        )
    )

    assert _compose_body(composition, _release(is_dvd=True)) == (
        "{title_exact} {source}"
    )


def test_an_omit_rule_drops_a_component_conditionally() -> None:
    # LST and ReelFliX omit the video codec on a DVD remux while keeping it
    # for a DVDRip encode.
    composition = Composition(
        components=("{source}", "{video_codec}", "{audio_codec}"),
        omit=(
            OmitRule(
                when=lambda release: release.is_dvd and release.is_remux,
                components=("{video_codec}",),
            ),
        ),
    )

    dvd_remux = _compose_body(composition, _release(is_dvd=True, is_remux=True))
    dvd_rip = _compose_body(composition, _release(is_dvd=True))

    assert dvd_remux == "{source} {audio_codec}"
    assert dvd_rip == "{source} {video_codec} {audio_codec}"


def test_the_tag_default_fills_an_untagged_release() -> None:
    # LST and BeyondHD want NOGROUP where a release carries no tag.
    composition = Composition(components=("{title_exact}",), tag_default="NOGROUP")

    assert compose_token_string(composition, _release()) == (
        "{title_exact}{:opt=-:release_group|default('NOGROUP')}"
    )


def test_no_tag_default_omits_the_tag_entirely() -> None:
    # Aither and ReelFliX prefer a blank tag to a NOGROUP placeholder.
    composition = Composition(components=("{title_exact}",), tag_default=None)

    assert compose_token_string(composition, _release()) == (
        "{title_exact}{:opt=-:release_group}"
    )


@pytest.mark.parametrize(
    ("episodes", "expected"),
    [((1,), "S01E01"), ((1, 2), "S01E01-02"), ((1, 2, 3), "S01E01-03")],
)
def test_a_simple_designator_states_a_range(
    episodes: tuple[int, ...], expected: str
) -> None:
    composition = Composition(components=(Designator.SIMPLE,))

    assert _compose_body(composition, _release(season=1, episodes=episodes)) == expected


@pytest.mark.parametrize(
    ("episodes", "expected"),
    [((1,), "S01E01"), ((1, 2), "S01E01E02"), ((1, 2, 3), "S01E01-03")],
)
def test_a_banded_designator_changes_form_at_three_episodes(
    episodes: tuple[int, ...], expected: str
) -> None:
    """LST mandates S##E##E## at exactly two episodes and S##E##-## above.

    No single user multi_episode_style satisfies both, which is why the
    designator is a composition field rather than the user's setting.
    """
    composition = Composition(components=(Designator.BANDED_BY_COUNT,))

    assert _compose_body(composition, _release(season=1, episodes=episodes)) == expected


@pytest.mark.parametrize("designator", [Designator.SIMPLE, Designator.BANDED_BY_COUNT])
def test_a_season_pack_designator_names_only_the_season(
    designator: Designator,
) -> None:
    # Aither's own example is "Tom Clancy's Jack Ryan S04 1080p AMZN ...".
    composition = Composition(components=(designator,))

    assert _compose_body(composition, _release(season=4)) == "S04"


@pytest.mark.parametrize("designator", [Designator.SIMPLE, Designator.BANDED_BY_COUNT])
def test_a_film_has_no_designator_at_all(designator: Designator) -> None:
    # The same entry serves both media types; a film simply has no season.
    composition = Composition(components=("{title_exact}", designator, "{resolution}"))

    assert _compose_body(composition, _release()) == ("{title_exact} {resolution}")
