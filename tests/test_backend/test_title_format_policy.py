from src.backend.trackers.title_format_policy import (
    TRACKER_TITLE_FORMAT_POLICY,
    TitleFormatPolicy,
    resolve_title_format_policy,
    title_format_policy,
)
from src.enums.series import EpisodeFormat
from src.enums.token_replacer import ColonReplace
from src.enums.tracker_selection import TrackerSelection
from src.payloads.trackers import TitleOverridePayload, TrackerInfo


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
    """The 8 trackers whose packaged default ships
    mvr_title_override_enabled = true must be locked (REQUIRED), matching
    default_config.toml.

    TorrentLeech is deliberately not among them: it dictates no title format,
    and the space-separated naming it does want is applied in code on every
    upload (TLUploader.generate_release_title)."""
    required_trackers = {
        TrackerSelection.AITHER,
        TrackerSelection.HUNO,
        TrackerSelection.LST,
        TrackerSelection.DARK_PEERS,
        TrackerSelection.SHARE_ISLAND,
        TrackerSelection.UPLOAD_CX,
        TrackerSelection.ONLY_ENCODES,
        TrackerSelection.REELFLIX,
    }
    for tracker in required_trackers:
        assert TRACKER_TITLE_FORMAT_POLICY[tracker] is TitleFormatPolicy.REQUIRED
    for tracker in (
        set(TrackerSelection) - required_trackers - {TrackerSelection.PASS_THE_POPCORN}
    ):
        assert TRACKER_TITLE_FORMAT_POLICY[tracker] is TitleFormatPolicy.FREE


def _movie_enforcer() -> TrackerInfo:
    return TrackerInfo(
        mvr_title_override_enabled=True,
        mvr_title_token_override="{title_clean} (enforced)",  # noqa: S106 - template token string, not a credential
    )


def _series_enforcer() -> TrackerInfo:
    return TrackerInfo(
        tvr_title_overrides={
            EpisodeFormat.STANDARD: TitleOverridePayload(
                enabled=True,
                colon_replace=ColonReplace.REPLACE_WITH_DASH,
                token="{title_clean} (enforced series)",  # noqa: S106 - template token string, not a credential
            )
        }
    )


def test_required_stays_locked_where_a_format_is_packaged() -> None:
    assert (
        resolve_title_format_policy(TrackerSelection.AITHER, _movie_enforcer())
        is TitleFormatPolicy.REQUIRED
    )
    assert (
        resolve_title_format_policy(
            TrackerSelection.AITHER, _series_enforcer(), EpisodeFormat.STANDARD
        )
        is TitleFormatPolicy.REQUIRED
    )


def test_required_falls_back_to_free_where_nothing_is_packaged() -> None:
    """The whole point of resolving per media type: a lock that enforces
    nothing takes the override away from the user and gives no guarantee back.

    HUNO is REQUIRED and dictates a movie format, but ships no
    tvr_title_overrides, so its series rows must be editable.
    """
    huno = _movie_enforcer()

    assert (
        resolve_title_format_policy(TrackerSelection.HUNO, huno)
        is TitleFormatPolicy.REQUIRED
    )
    for fmt in EpisodeFormat:
        assert (
            resolve_title_format_policy(TrackerSelection.HUNO, huno, fmt)
            is TitleFormatPolicy.FREE
        )


def test_a_packaged_replace_map_alone_counts_as_enforcement() -> None:
    """A tracker can enforce a character rule with no token of its own, so the
    global template supplies the wording. Recognised on both sides."""
    movie_only_rules = TrackerInfo(
        mvr_title_override_enabled=True,
        mvr_title_replace_map=[("(?i)hdr10plus", "HDR10+")],
    )
    series_only_rules = TrackerInfo(
        tvr_title_overrides={
            EpisodeFormat.STANDARD: TitleOverridePayload(
                enabled=True,
                replace_map=[("(?i)hdr10plus", "HDR10+")],
            )
        }
    )

    assert (
        resolve_title_format_policy(TrackerSelection.AITHER, movie_only_rules)
        is TitleFormatPolicy.REQUIRED
    )
    assert (
        resolve_title_format_policy(
            TrackerSelection.AITHER, series_only_rules, EpisodeFormat.STANDARD
        )
        is TitleFormatPolicy.REQUIRED
    )


def test_a_packaged_but_disabled_format_does_not_lock() -> None:
    disabled = TrackerInfo(
        mvr_title_override_enabled=False,
        mvr_title_token_override="{title_clean} (ignored)",  # noqa: S106 - template token string, not a credential
    )

    assert (
        resolve_title_format_policy(TrackerSelection.AITHER, disabled)
        is TitleFormatPolicy.FREE
    )


def test_free_and_unsupported_ignore_the_packaged_data() -> None:
    """Only REQUIRED is narrowed. A FREE tracker stays editable and PTP stays
    locked out even if packaged data appeared under them."""
    assert (
        resolve_title_format_policy(TrackerSelection.BEYOND_HD, _movie_enforcer())
        is TitleFormatPolicy.FREE
    )
    assert (
        resolve_title_format_policy(
            TrackerSelection.PASS_THE_POPCORN, _movie_enforcer()
        )
        is TitleFormatPolicy.UNSUPPORTED
    )
    assert (
        resolve_title_format_policy(
            TrackerSelection.PASS_THE_POPCORN, TrackerInfo(), EpisodeFormat.STANDARD
        )
        is TitleFormatPolicy.UNSUPPORTED
    )
