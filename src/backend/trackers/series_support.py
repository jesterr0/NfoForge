from src.enums.tracker_selection import TrackerSelection

UNSUPPORTED_SERIES_TRACKERS = frozenset(
    {
        TrackerSelection.PASS_THE_POPCORN,
        TrackerSelection.REELFLIX,
    }
)


def supports_series_upload(tracker: TrackerSelection) -> bool:
    return tracker not in UNSUPPORTED_SERIES_TRACKERS
