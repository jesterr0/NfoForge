import pytest

from src.backend.trackers.title_rules import TITLE_RULES, Separator
from src.enums.token_replacer import ColonReplace
from src.enums.tracker_selection import TrackerSelection


def test_every_tracker_has_an_entry() -> None:
    # A tracker absent from the registry renders the user's template with no
    # normalisation at all, which is right for a plugin-contributed tracker
    # and wrong for one NfoForge ships.
    assert set(TITLE_RULES) == set(TrackerSelection)


def test_no_two_entries_share_an_object() -> None:
    """Principle 1: one entry per tracker, no shared families.

    Two entries that happen to be identical stay written out separately, so
    a single tracker changing its rules cannot require unpicking a shared
    abstraction -- or worse, silently alter its neighbour. The shipped
    config's worst defect was exactly this failure in prose form: ReelFliX's
    template was a near copy of BeyondHD's, and their published rules
    differ.
    """
    seen: dict[int, TrackerSelection] = {}
    for tracker, entry in TITLE_RULES.items():
        for part in (entry, entry.normalisation, entry.composition):
            if part is None:
                continue
            previous = seen.get(id(part))
            assert previous is None, f"{tracker} shares an object with {previous}"
            seen[id(part)] = tracker


@pytest.mark.parametrize(
    "tracker",
    [TrackerSelection.PASS_THE_POPCORN, TrackerSelection.HUNO],
)
def test_trackers_with_no_release_name_field_say_so(
    tracker: TrackerSelection,
) -> None:
    # PTP derives its release from structured fields plus the name inside
    # the torrent; HUNO auto mode builds its name from the torrent filename,
    # MediaInfo and TMDB. There is nothing for a title to shape on either.
    assert TITLE_RULES[tracker].has_release_name_field is False
    assert TITLE_RULES[tracker].composition is None


def test_every_other_tracker_has_a_release_name_field() -> None:
    # The guard for the test above: "no release name field" is the rare
    # state, and a typo that spread it would silently stop composing.
    without = {
        tracker
        for tracker, entry in TITLE_RULES.items()
        if not entry.has_release_name_field
    }

    assert without == {TrackerSelection.PASS_THE_POPCORN, TrackerSelection.HUNO}


def test_seedpool_is_the_only_dotted_entry() -> None:
    # SeedPool names uploads after the release; every other tracker here
    # wants the spaced form the UNIT3D family strips to.
    dotted = {
        tracker
        for tracker, entry in TITLE_RULES.items()
        if entry.normalisation.separator is Separator.DOTTED
    }

    assert dotted == {TrackerSelection.SEEDPOOL}


def test_only_hdbits_publishes_a_character_allowlist() -> None:
    # Inventing one for another tracker would strip punctuation its own
    # published examples carry. An absent allowlist is a deliberate state.
    with_allowlist = {
        tracker
        for tracker, entry in TITLE_RULES.items()
        if entry.normalisation.allowlist is not None
    }

    assert with_allowlist == {TrackerSelection.HDB}


def test_an_absent_colon_rule_means_defer_to_the_user() -> None:
    """`None` is not a colon strategy; it is the absence of one.

    Field-level precedence needs the two states distinguishable: an entry
    that names `KEEP` is imposing it, while an entry that names nothing
    lets the user's global title colon apply.
    """
    assert TITLE_RULES[TrackerSelection.TORRENT_LEECH].normalisation.colon is None
    assert TITLE_RULES[TrackerSelection.AITHER].normalisation.colon is not None


def test_the_colon_rules_match_what_the_shipped_config_actually_applied() -> None:
    """The transcription, pinned rather than checked once.

    A shipped colon value only reached a title when that tracker's override
    was enabled, so the eight trackers shipping `enabled = false` applied
    the user's global setting no matter what their colon field said. Those
    become `None` here, which preserves their behaviour exactly; the nine
    with an enabled override carry their value forward.

    HUNO is the odd one: it ships enabled, but has no release name field,
    so its colon has never reached anything.
    """
    keep = {
        TrackerSelection.BEYOND_HD,
        TrackerSelection.REELFLIX,
        TrackerSelection.AITHER,
        TrackerSelection.LST,
    }
    dash = {
        TrackerSelection.DARK_PEERS,
        TrackerSelection.SHARE_ISLAND,
        TrackerSelection.UPLOAD_CX,
        TrackerSelection.ONLY_ENCODES,
    }

    for tracker, entry in TITLE_RULES.items():
        colon = entry.normalisation.colon
        if tracker in keep:
            assert colon is ColonReplace.KEEP, tracker
        elif tracker in dash:
            assert colon is ColonReplace.REPLACE_WITH_DASH, tracker
        else:
            assert colon is None, tracker
