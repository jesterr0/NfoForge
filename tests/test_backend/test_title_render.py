import re

import pytest

from src.backend.trackers.title_render import (
    compose_token_string,
    normalise_title,
    resolve_dynamic_range,
)
from src.backend.trackers.title_rules import (
    TITLE_RULES,
    Composition,
    ConditionalOrder,
    ConditionalRewrite,
    Designator,
    DynamicRangeRule,
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


# What the HDBits entry produces, captured from its own uploader while both
# existed. The uploader's formatter is gone now, so these are the record of
# what it did: separator, plain rewrites, a conditional rewrite, and an
# allowlist with its cleanup, on one tracker.
HDB_CORPUS = [
    (
        "Movie Name 2024 2160p UHD BluRay REMUX DV HDR HEVC TrueHD 7.1 Atmos-GRP",
        "Movie Name 2024 2160p UHD BluRay Remux DoVi HDR10 HEVC TrueHD 7.1 Atmos-GRP",
    ),
    (
        "Movie.Name.2024.1080p.AMZN.WEB-DL.DD+.5.1.H.265-GRP",
        "Movie Name 2024 1080p AMZN WEB-DL DD+ 5.1 HEVC-GRP",
    ),
    (
        # H.264 is taken as written; only the one codec is rewritten.
        "Movie.Name.2024.1080p.AMZN.WEB-DL.DD+.5.1.H.264-GRP",
        "Movie Name 2024 1080p AMZN WEB-DL DD+ 5.1 H.264-GRP",
    ),
    (
        # The conditional rewrite stands down: HDR10+ is already present.
        "Show Name 2024 S01E10 2160p PMTP WEB-DL DD+ 5.1 DV HDR10+ H.265-GRP",
        "Show Name 2024 S01E10 2160p PMTP WEB-DL DD+ 5.1 DoVi HDR10+ HEVC-GRP",
    ),
    (
        # DVDRip survives a DV -> DoVi rule, which a substring replace would
        # have turned into DoViDRip.
        "Transformers 2007 DVDRip DD 5.1 x264-GRP",
        "Transformers 2007 DVDRip DD 5.1 x264-GRP",
    ),
    (
        # The allowlist strips, and the gap it leaves closes.
        'Who Are You? 2024 1080p BluRay <"*> DD 2.0 x264-GRP',
        "Who Are You 2024 1080p BluRay DD 2.0 x264-GRP",
    ),
    (
        "Movie Name 2024 1080p BluRay TrueHD 7.1.4 Atmos x265-GRP",
        "Movie Name 2024 1080p BluRay TrueHD 7.1.4 Atmos x265-GRP",
    ),
]


@pytest.mark.parametrize(("title", "expected"), HDB_CORPUS)
def test_the_hdbits_entry_normalises_as_its_uploader_did(
    title: str, expected: str
) -> None:
    """The transcription, now that there is nothing left to compare against.

    HDBits is the most heavily normalised tracker in the codebase, so one
    corpus exercises every stage. These expectations were taken from its own
    formatter before that formatter was deleted, with one deliberate
    difference already recorded: it left a double space where the allowlist
    stripped a token, and the entry closes the gap.
    """
    entry = TITLE_RULES[TrackerSelection.HDB].normalisation

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


def test_the_entry_closes_a_gap_the_old_formatter_left_open() -> None:
    """The one place the entry differed from hdb.py's formatter.

    That formatter cleaned up the period case (`" ."`) but not the space
    case, so a title carrying a forbidden token shipped to HDBits with a
    visible gap in it. Kept as its own test because it is the single
    behaviour change in the transcription.
    """
    title = 'Who Are You? 2024 1080p BluRay <"*> DD 2.0 x264-GRP'
    entry = TITLE_RULES[TrackerSelection.HDB].normalisation

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


# -------------------------------------------------------------- dynamic range

# The three shapes the checked trackers divide into.
_OMITS_SDR = DynamicRangeRule()
_EMITS_SDR = DynamicRangeRule(emit_sdr_above_1080=True)
_BEYOND_HD = DynamicRangeRule(
    emit_sdr_above_1080=True, assumes_hdr10_on_disc_or_remux=True
)


@pytest.mark.parametrize(
    ("resolution", "disc_or_remux", "identity", "expected"),
    [
        # At or below 1080p nothing is assumed, so the type is stated as it is
        # and SDR is not stated at all.
        (1080, False, "SDR", ""),
        (1080, False, "HDR10", "HDR"),
        (1080, True, "SDR", ""),
        (1080, True, "HDR10", "HDR"),
        # On a 2160p disc or remux the assumed HDR10 baseline is dropped.
        (2160, True, "HDR10", ""),
        (2160, True, "DV HDR10", "DV"),
        # Neither of these is plain HDR10, so neither is touched.
        (2160, True, "HDR10+", "HDR10Plus"),
        (2160, True, "DV HDR10+", "DV HDR10Plus"),
        # Where HDR is assumed, silence reads as HDR -- so the exception has
        # to be spelled out.
        (2160, True, "SDR", "SDR"),
        # Nothing is assumed off a disc or remux, so everything is stated.
        (2160, False, "SDR", "SDR"),
        (2160, False, "HDR10", "HDR"),
        (2160, False, "DV HDR10", "DV HDR"),
    ],
)
def test_beyondhd_dynamic_range(
    resolution: int, disc_or_remux: bool, identity: str, expected: str
) -> None:
    """BeyondHD assumes HDR10 on a 2160p disc or remux and nowhere else.

    One rule, not twelve rows: on a 2160p disc or remux the assumed HDR10
    baseline is dropped, so HDR10 becomes nothing and DV HDR10 becomes DV,
    while HDR10+ and DV HDR10+ pass through untouched because neither is
    plain HDR10.

    The shipped config got this wrong in both directions -- HDR on a 2160p
    remux where BHD assumes it, and nothing on a 2160p WEB SDR release
    where BHD requires it.
    """
    release = _release(
        resolution=resolution, is_remux=disc_or_remux, hdr_identity=identity
    )

    assert resolve_dynamic_range(_BEYOND_HD, release) == expected


@pytest.mark.parametrize("disc", [True, False])
def test_a_disc_counts_the_same_as_a_remux(disc: bool) -> None:
    # The rule is "disc or remux", and BHD's own wording names both.
    release = _release(
        resolution=2160,
        is_disc=disc,
        is_remux=not disc,
        hdr_identity="DV HDR10",
    )

    assert resolve_dynamic_range(_BEYOND_HD, release) == "DV"


@pytest.mark.parametrize("rule", [_OMITS_SDR, _EMITS_SDR, _BEYOND_HD])
@pytest.mark.parametrize("resolution", [720, 1080])
def test_sdr_is_never_emitted_at_or_below_1080p(
    rule: DynamicRangeRule, resolution: int
) -> None:
    """1080p is SDR by default, so the component carries no information.

    Convention rather than a published rule, which is why it lives in the
    resolver rather than being restated in each entry -- and why there is
    no "always include SDR" state to reach. That output is wanted by
    nobody.
    """
    release = _release(resolution=resolution, hdr_identity="SDR")

    assert resolve_dynamic_range(rule, release) == ""


def test_an_entry_that_omits_sdr_omits_it_above_1080p_too() -> None:
    # Aither and LST publish the omit-SDR form at every resolution.
    release = _release(resolution=2160, hdr_identity="SDR")

    assert resolve_dynamic_range(_OMITS_SDR, release) == ""
    assert resolve_dynamic_range(_EMITS_SDR, release) == "SDR"


@pytest.mark.parametrize("identity", ["PQ", "HLG"])
def test_pq_and_hlg_pass_through_a_disc_or_remux_unchanged(identity: str) -> None:
    # Not covered by the supplied rules. The baseline drop names HDR10 and
    # DV HDR10 only, so these pass through and no rule is invented.
    release = _release(resolution=2160, is_disc=True, hdr_identity=identity)

    assert resolve_dynamic_range(_BEYOND_HD, release) == identity


def test_a_user_spelling_applies_where_the_tracker_publishes_none() -> None:
    # BHD accepts HDR10+, HDR10P and HDR10Plus alike, so it has no rule and
    # the user's choice reaches the title.
    release = _release(resolution=2160, hdr_identity="HDR10+")

    assert (
        resolve_dynamic_range(_BEYOND_HD, release, custom_strings={"HDR10+": "HDR10P"})
        == "HDR10P"
    )


def test_a_published_spelling_outranks_the_users() -> None:
    """LST publishes PQ10, so a user spelling of PQ does not survive there.

    Keyed on the identity rather than on the rendered string: a map keyed
    on what was spelled would miss a user who spells PQ unusually, which is
    exactly the case the override exists for.
    """
    rule = DynamicRangeRule(spellings={"PQ": "PQ10"})
    release = _release(resolution=2160, hdr_identity="PQ")

    assert (
        resolve_dynamic_range(rule, release, custom_strings={"PQ": "PeeQue"}) == "PQ10"
    )


def test_a_published_suppression_removes_the_component() -> None:
    # Aither suppresses PQ rather than spelling it.
    rule = DynamicRangeRule(spellings={"PQ": None})
    release = _release(resolution=2160, hdr_identity="PQ")

    assert resolve_dynamic_range(rule, release, custom_strings={"PQ": "PQ"}) == ""


def test_the_resolver_cannot_see_the_user_toggles() -> None:
    """A tracker rule must not be subject to a user preference.

    `resolutions` and `hdr_types` blank the component by resolution or by
    type, which is right for a filename the user owns. BeyondHD's 2160p WEB
    row requires SDR from a user who may have SDR switched off, so those
    switches do not reach here -- enforced by the signature rather than by
    remembering not to pass them.
    """
    import inspect

    parameters = inspect.signature(resolve_dynamic_range).parameters

    assert list(parameters) == ["rule", "release", "custom_strings"]


def test_a_dynamic_range_component_composes_in_place() -> None:
    composition = Composition(
        components=("{source}", _BEYOND_HD, "{video_codec}"),
    )
    release = _release(resolution=2160, is_remux=True, hdr_identity="DV HDR10")

    assert _compose_body(composition, release) == "{source} DV {video_codec}"


def test_a_dropped_dynamic_range_leaves_no_component_behind() -> None:
    # A 2160p remux that is HDR10 only emits nothing, and the components
    # either side must close up.
    composition = Composition(
        components=("{source}", _BEYOND_HD, "{video_codec}"),
    )
    release = _release(resolution=2160, is_remux=True, hdr_identity="HDR10")

    assert _compose_body(composition, release) == "{source} {video_codec}"


@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        ("SDR", "SDR"),
        ("PQ", "PQ"),
        ("HLG", "HLG"),
        ("HDR10", "HDR"),
        ("HDR10+", "HDR10Plus"),
        ("DV", "DV"),
        ("DV HDR10", "DV HDR"),
        ("DV HDR10+", "DV HDR10Plus"),
    ],
)
def test_the_default_spelling_is_what_the_token_already_emits(
    identity: str, expected: str
) -> None:
    """An identity's default spelling is NfoForge's, not the identity name.

    The eight `HdrType` values are identities, and four of them are not
    spelled the way `{video_dynamic_range_type}` renders them: HDR10 is
    written "HDR", HDR10+ is "HDR10Plus", and the two Dolby Vision
    composites follow. That token is what every packaged tracker template
    uses, so it is what every tracker has been receiving, and both Aither's
    "REMUX HDR HEVC" and LST's "REMUX DV HDR HEVC" confirm it.

    It is also what the per-tracker spelling overrides are written against:
    the three trackers that publish "HDR10+" map it from "HDR10Plus", which
    only makes sense if that is the default.
    """
    release = _release(resolution=2160, hdr_identity=identity)

    assert resolve_dynamic_range(_EMITS_SDR, release) == expected


def test_a_user_spelling_overrides_the_default_spelling() -> None:
    # The user's custom_strings are keyed on the identity, so a preference
    # for HDR10 reaches the title even though the default spells it "HDR".
    release = _release(resolution=2160, hdr_identity="HDR10")

    assert resolve_dynamic_range(_EMITS_SDR, release) == "HDR"
    assert (
        resolve_dynamic_range(_EMITS_SDR, release, custom_strings={"HDR10": "HDR10"})
        == "HDR10"
    )


# ------------------------------------------------------------- the entries
#
# These assert the composed token *order*, which is what an entry controls.
# The published golden strings need a rendered title, so they land with the
# wiring that renders one.


def _composed(tracker: TrackerSelection, **release: object) -> str:
    composition = TITLE_RULES[tracker].composition
    assert composition is not None
    return compose_token_string(composition, _release(**release))


COMPOSING = [
    TrackerSelection.LST,
    TrackerSelection.AITHER,
    TrackerSelection.REELFLIX,
    TrackerSelection.BEYOND_HD,
    TrackerSelection.DARK_PEERS,
    TrackerSelection.SHARE_ISLAND,
    TrackerSelection.UPLOAD_CX,
    TrackerSelection.ONLY_ENCODES,
]


def test_exactly_the_expected_trackers_compose() -> None:
    composing = {t for t, e in TITLE_RULES.items() if e.composition is not None}

    assert composing == set(COMPOSING)


@pytest.mark.parametrize(
    "tracker",
    [TrackerSelection.LST, TrackerSelection.AITHER, TrackerSelection.REELFLIX],
)
def test_video_leads_on_a_remux_and_trails_on_an_encode(
    tracker: TrackerSelection,
) -> None:
    """The order swap all three publish, and the ReelFliX defect.

    ReelFliX's shipped template was a near copy of BeyondHD's, which does
    not swap, so every ReelFliX remux emitted audio before video where its
    own rules require video first.
    """
    remux = _composed(tracker, is_remux=True, resolution=2160)
    encode = _composed(tracker, resolution=1080)

    assert remux.index("{video_codec}") < remux.index("{audio_codec_no_atmos}")
    assert encode.index("{audio_codec_no_atmos}") < encode.index("{video_codec}")


def test_aither_carries_an_episode_title_and_lst_does_not() -> None:
    # The two genuinely differ, and Aither's published examples carry one.
    aither = _composed(TrackerSelection.AITHER, season=1, episodes=(1,))
    lst = _composed(TrackerSelection.LST, season=1, episodes=(1,))

    assert "{episode_title_exact}" in aither
    assert "{episode_title_exact}" not in lst


@pytest.mark.parametrize("tracker", COMPOSING)
def test_the_year_is_omitted_for_a_series(tracker: TrackerSelection) -> None:
    """Aither and BHD both make the year conditional on a name
    collision that is not determinable, so omitting it is correct."""
    film = _composed(tracker)
    series = _composed(tracker, season=1, episodes=(1,))

    assert "{release_year}" in film
    assert "{release_year}" not in series


@pytest.mark.parametrize("tracker", [TrackerSelection.LST, TrackerSelection.REELFLIX])
def test_dvd_omits_the_resolution_and_a_dvd_remux_omits_the_codec(
    tracker: TrackerSelection,
) -> None:
    # LST's own example: "Transformers 2007 DVDRip DD 5.1 x264-NOGROUP" --
    # no resolution, but a DVDRip encode keeps its codec.
    dvd_rip = _composed(tracker, is_dvd=True)
    dvd_remux = _composed(tracker, is_dvd=True, is_remux=True)

    assert "{resolution}" not in dvd_rip
    assert "{video_codec}" in dvd_rip
    assert "{video_codec}" not in dvd_remux


@pytest.mark.parametrize(
    "tracker",
    [TrackerSelection.LST, TrackerSelection.AITHER, TrackerSelection.REELFLIX],
)
def test_the_dub_component_sits_immediately_before_the_audio_codec(
    tracker: TrackerSelection,
) -> None:
    composed = _composed(tracker)
    parts = composed.split(" ")

    assert parts[parts.index("{audio_codec_no_atmos}") - 1] == (
        "{localization|unless(audio_language_dual)}"
    )
    assert "{audio_language_dual}" in parts


def test_beyondhd_keeps_its_audio_codec_undivided() -> None:
    """BeyondHD wants "DDP Atmos 5.1", which {audio_codec} emits natively.

    The audio_codec_no_atmos plus separate {atmos} split produces
    "DDP 5.1 Atmos", which is the LST, Aither and ReelFliX spelling.
    """
    composed = _composed(TrackerSelection.BEYOND_HD)

    assert "{audio_codec}" in composed
    assert "{audio_codec_no_atmos}" not in composed
    assert "{atmos}" not in composed


def test_beyondhd_does_not_rewrite_ddp() -> None:
    # BHD uses DDP throughout, where the other three list DD+.
    assert "DDP" not in TITLE_RULES[TrackerSelection.BEYOND_HD].normalisation.vocabulary
    assert TITLE_RULES[TrackerSelection.LST].normalisation.vocabulary["DDP"] == "DD+"


def test_beyondhd_keeps_hybrid_against_remux() -> None:
    # BeyondHD requires "HYBRID REMUX" adjacent.
    parts = _composed(TrackerSelection.BEYOND_HD).split(" ")

    assert parts[parts.index("{remux}") - 1] == "{hybrid}"


def test_beyondhd_leads_with_the_codec_on_a_dvd() -> None:
    # 3.4.6: "MPEG-2 DD2.0", not "DD2.0 MPEG-2".
    dvd = _composed(TrackerSelection.BEYOND_HD, is_dvd=True)

    assert dvd.index("{video_codec}") < dvd.index("{audio_codec}")


@pytest.mark.parametrize(
    "tracker",
    [
        TrackerSelection.DARK_PEERS,
        TrackerSelection.SHARE_ISLAND,
        TrackerSelection.UPLOAD_CX,
        TrackerSelection.ONLY_ENCODES,
    ],
)
def test_the_assumed_four_are_transcribed_not_improved(
    tracker: TrackerSelection,
) -> None:
    """No published rules were gathered for these, so the shipped config is
    the only source for what it covers, and is copied rather than corrected.

    It covers films only, which is why the two departures below are not
    contradictions: the config said nothing about either.
    """
    composed = _composed(tracker)

    assert "{edition}" in composed
    assert "{cut}" not in composed
    assert "{audio_codec}" in composed


@pytest.mark.parametrize(
    "tracker",
    [
        TrackerSelection.DARK_PEERS,
        TrackerSelection.SHARE_ISLAND,
        TrackerSelection.UPLOAD_CX,
        TrackerSelection.ONLY_ENCODES,
    ],
)
def test_the_assumed_four_name_titles_at_the_exact_tier(
    tracker: TrackerSelection,
) -> None:
    """A tracker rule that varies with a user setting is not a rule.

    The shipped config said `{title_clean}`, which answers to
    `title_clean_rules` -- and those ship aggressive enough to unidecode,
    drop apostrophes and flatten every non-alphanumeric to a space. Two
    trackers would then spell the same film differently on the strength of
    a setting neither publishes. The colon is the clearest case: cleaning
    erased it before the entry's own colon rule could apply, so the entry
    said replace-with-dash and got deletion.

    Every entry with gathered rules already names titles exactly, so this
    is what the four look like when the split stops tracking which of them
    happened to be transcribed.
    """
    composed = _composed(tracker)

    assert "{title_exact}" in composed
    assert "{title_clean}" not in composed
    assert "{episode_title_exact}" in composed
    assert "{episode_title_clean}" not in composed


def test_only_shareisland_carries_a_language_component() -> None:
    carrying = {
        tracker
        for tracker in COMPOSING
        if "audio_language_all_full" in _composed(tracker)
    }

    assert carrying == {TrackerSelection.SHARE_ISLAND}
