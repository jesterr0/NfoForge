from src.backend.trackers.title_format_policy import (
    TRACKER_TITLE_FORMAT_POLICY,
    TitleFormatPolicy,
    title_format_policy,
)
from src.enums.tracker_selection import TrackerSelection


def test_every_tracker_has_a_title_format_policy() -> None:
    """TRACKER_TITLE_FORMAT_POLICY is the single source of truth for whether
    a tracker's title override is free, enforced, or unsupported; a newly
    added TrackerSelection must not be silently omitted from it."""
    missing = set(TrackerSelection) - set(TRACKER_TITLE_FORMAT_POLICY)
    assert not missing, f"trackers missing a title-format-policy row: {missing}"


def test_title_format_policy_helper_matches_the_table() -> None:
    for tracker, policy in TRACKER_TITLE_FORMAT_POLICY.items():
        assert title_format_policy(tracker) is policy


def test_pass_the_popcorn_is_unsupported() -> None:
    assert (
        TRACKER_TITLE_FORMAT_POLICY[TrackerSelection.PASS_THE_POPCORN]
        is TitleFormatPolicy.UNSUPPORTED
    )


def test_trackers_shipping_a_default_override_are_required() -> None:
    """The 9 trackers whose packaged default already ships
    mvr_title_override_enabled = true must be locked (REQUIRED), matching
    default_config.toml."""
    required_trackers = {
        TrackerSelection.MORE_THAN_TV,
        TrackerSelection.TORRENT_LEECH,
        TrackerSelection.AITHER,
        TrackerSelection.HUNO,
        TrackerSelection.LST,
        TrackerSelection.DARK_PEERS,
        TrackerSelection.SHARE_ISLAND,
        TrackerSelection.UPLOAD_CX,
        TrackerSelection.ONLY_ENCODES,
    }
    for tracker in required_trackers:
        assert TRACKER_TITLE_FORMAT_POLICY[tracker] is TitleFormatPolicy.REQUIRED
    for tracker in (
        set(TrackerSelection) - required_trackers - {TrackerSelection.PASS_THE_POPCORN}
    ):
        assert TRACKER_TITLE_FORMAT_POLICY[tracker] is TitleFormatPolicy.FREE
