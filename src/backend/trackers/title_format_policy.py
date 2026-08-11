from enum import Enum, auto

from src.enums.tracker_selection import TrackerSelection


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


# Single source of truth for each tracker's title-override policy. The test
# suite enforces completeness so a newly added tracker can't be silently
# omitted -- see tests/test_backend/test_title_format_policy.py. Both the
# backend (process.generate_tracker_title) and the frontend settings pages
# (MoviesManagementSettings, SeriesManagementSettings) key off this dict, so
# it's the only place a tracker's policy needs to change.
TRACKER_TITLE_FORMAT_POLICY: dict[TrackerSelection, TitleFormatPolicy] = {
    TrackerSelection.TORRENT_LEECH: TitleFormatPolicy.REQUIRED,
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
    """Return the title-format policy for ``tracker``."""
    return TRACKER_TITLE_FORMAT_POLICY[tracker]
