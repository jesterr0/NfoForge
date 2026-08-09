from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection

_MOVIE_AND_SERIES = frozenset({MediaType.MOVIE, MediaType.SERIES})
_MOVIE_ONLY = frozenset({MediaType.MOVIE})

# Single source of truth for which media types each tracker can accept in
# NfoForge. Every TrackerSelection must have exactly one row here; the test
# suite enforces completeness so a newly added tracker can't be silently
# omitted. List a narrower set only for trackers that genuinely can't take a
# media type.
TRACKER_SUPPORTED_MEDIA: dict[TrackerSelection, frozenset[MediaType]] = {
    TrackerSelection.MORE_THAN_TV: _MOVIE_AND_SERIES,
    TrackerSelection.TORRENT_LEECH: _MOVIE_AND_SERIES,
    TrackerSelection.BEYOND_HD: _MOVIE_AND_SERIES,
    TrackerSelection.PASS_THE_POPCORN: _MOVIE_ONLY,
    TrackerSelection.REELFLIX: _MOVIE_ONLY,
    TrackerSelection.AITHER: _MOVIE_AND_SERIES,
    TrackerSelection.HUNO: _MOVIE_AND_SERIES,
    TrackerSelection.LST: _MOVIE_AND_SERIES,
    TrackerSelection.DARK_PEERS: _MOVIE_AND_SERIES,
    TrackerSelection.SHARE_ISLAND: _MOVIE_AND_SERIES,
    TrackerSelection.UPLOAD_CX: _MOVIE_AND_SERIES,
    TrackerSelection.ONLY_ENCODES: _MOVIE_AND_SERIES,
    TrackerSelection.HDB: _MOVIE_AND_SERIES,
    TrackerSelection.BLUTOPIA: _MOVIE_AND_SERIES,
    TrackerSelection.SEEDPOOL: _MOVIE_AND_SERIES,
    TrackerSelection.UTOPIA: _MOVIE_AND_SERIES,
    TrackerSelection.YU_SCENE: _MOVIE_AND_SERIES,
    TrackerSelection.FEAR_NO_PEER: _MOVIE_AND_SERIES,
}


def supports_media(tracker: TrackerSelection, media_type: MediaType) -> bool:
    """Return whether ``tracker`` can accept an upload of ``media_type``."""
    return media_type in TRACKER_SUPPORTED_MEDIA[tracker]


def supports_series_upload(tracker: TrackerSelection) -> bool:
    return supports_media(tracker, MediaType.SERIES)


# Derived exclusion sets, kept for callers that gate on a single media type
# (dupe checks, the upload guard, the tracker-selection wizard). These always
# stay in sync with TRACKER_SUPPORTED_MEDIA above.
UNSUPPORTED_SERIES_TRACKERS = frozenset(
    tracker
    for tracker in TRACKER_SUPPORTED_MEDIA
    if not supports_media(tracker, MediaType.SERIES)
)
UNSUPPORTED_MOVIE_TRACKERS = frozenset(
    tracker
    for tracker in TRACKER_SUPPORTED_MEDIA
    if not supports_media(tracker, MediaType.MOVIE)
)
