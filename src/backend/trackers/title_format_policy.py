from enum import Enum, auto

from src.enums.series import EpisodeFormat
from src.enums.tracker_selection import TrackerSelection
from src.payloads.trackers import TrackerInfo


class TitleFormatPolicy(Enum):
    """How much control a user has over a tracker's generated title.

    FREE: the user's title override, if enabled, is fully editable -- the
        tracker has no known naming requirement beyond what NfoForge's global
        movie/series templates already produce.
    REQUIRED: the tracker enforces its own title format (rejected or
        mis-categorized uploads otherwise). The packaged default override
        always applies and cannot be edited or disabled by the user.
    UNSUPPORTED: the tracker does not support a title override at all; the
        override stays off and cannot be enabled.
    """

    FREE = auto()
    REQUIRED = auto()
    UNSUPPORTED = auto()


# Single source of truth for each tracker's declared title-override policy.
# The test suite enforces completeness so a newly added tracker can't be
# silently omitted -- see tests/test_backend/test_title_format_policy.py.
# The backend (process.generate_tracker_title) and the frontend settings pages
# (MoviesManagementSettings, SeriesManagementSettings) reach this through
# `resolve_title_format_policy`, which narrows REQUIRED to the media types the
# tracker actually ships a format for.
TRACKER_TITLE_FORMAT_POLICY: dict[TrackerSelection, TitleFormatPolicy] = {
    # TorrentLeech dictates no title format. It wants space-separated names,
    # but that is enforced in code for every upload by
    # TLUploader.generate_release_title, which protects audio channel layouts
    # while it strips separators. The packaged override used to carry a blind
    # `\.` -> space rule that ran earlier, at title generation, and turned
    # "TrueHD Atmos 7.1" into "TrueHD Atmos 7 1" before the safe formatter
    # could see it. Neither Upload Assistant nor upbrr has a TL naming rule.
    TrackerSelection.TORRENT_LEECH: TitleFormatPolicy.FREE,
    TrackerSelection.AITHER: TitleFormatPolicy.REQUIRED,
    TrackerSelection.HUNO: TitleFormatPolicy.REQUIRED,
    TrackerSelection.LST: TitleFormatPolicy.REQUIRED,
    TrackerSelection.DARK_PEERS: TitleFormatPolicy.REQUIRED,
    TrackerSelection.SHARE_ISLAND: TitleFormatPolicy.REQUIRED,
    TrackerSelection.UPLOAD_CX: TitleFormatPolicy.REQUIRED,
    TrackerSelection.ONLY_ENCODES: TitleFormatPolicy.REQUIRED,
    TrackerSelection.REELFLIX: TitleFormatPolicy.REQUIRED,
    TrackerSelection.PASS_THE_POPCORN: TitleFormatPolicy.UNSUPPORTED,
    TrackerSelection.BEYOND_HD: TitleFormatPolicy.FREE,
    TrackerSelection.HDB: TitleFormatPolicy.FREE,
    TrackerSelection.BLUTOPIA: TitleFormatPolicy.FREE,
    TrackerSelection.SEEDPOOL: TitleFormatPolicy.FREE,
    TrackerSelection.UTOPIA: TitleFormatPolicy.FREE,
    TrackerSelection.YU_SCENE: TitleFormatPolicy.FREE,
    TrackerSelection.FEAR_NO_PEER: TitleFormatPolicy.FREE,
}


def title_format_policy(tracker: TrackerSelection) -> TitleFormatPolicy:
    """Return the declared title-format policy for ``tracker``.

    This is the tracker-wide declaration. What a tracker actually enforces is
    stored per media type, so use `resolve_title_format_policy` for anything
    that locks a control or picks an override source.
    """
    return TRACKER_TITLE_FORMAT_POLICY[tracker]


def enforces_movie_title(packaged: TrackerInfo) -> bool:
    """Does the packaged default enforce a movie title?

    Both forms count: a token, or a character rule with no token, which leaves
    the user's global movie template to supply the wording.
    """
    return bool(
        packaged.mvr_title_override_enabled
        and (
            packaged.mvr_title_token_override.strip() or packaged.mvr_title_replace_map
        )
    )


def enforces_series_title(packaged: TrackerInfo, episode_format: EpisodeFormat) -> bool:
    """Does the packaged default enforce a series title for this format?"""
    entry = (packaged.tvr_title_overrides or {}).get(episode_format)
    return bool(entry and entry.enabled and (entry.token.strip() or entry.replace_map))


def resolve_title_format_policy(
    tracker: TrackerSelection,
    packaged: TrackerInfo,
    episode_format: EpisodeFormat | None = None,
) -> TitleFormatPolicy:
    """The policy that actually applies, for one tracker and one media type.

    REQUIRED is declared per tracker, but enforcement is packaged per media
    type: `mvr_title_*` for movies, `tvr_title_overrides[episode_format]` for
    series. A tracker can dictate a movie format and ship nothing for series
    (most REQUIRED trackers do). Locking that series row would take the
    override away from the user and enforce nothing in return, so it resolves
    to FREE and behaves like any other editable override.

    Adding a packaged format later re-locks the row on its own -- the lock
    follows the data rather than a second table that has to be kept in step.

    ``episode_format`` selects the media type: None for movies, an
    `EpisodeFormat` for series.
    """
    policy = TRACKER_TITLE_FORMAT_POLICY[tracker]
    if policy is not TitleFormatPolicy.REQUIRED:
        return policy

    enforced = (
        enforces_movie_title(packaged)
        if episode_format is None
        else enforces_series_title(packaged, episode_format)
    )
    return TitleFormatPolicy.REQUIRED if enforced else TitleFormatPolicy.FREE
