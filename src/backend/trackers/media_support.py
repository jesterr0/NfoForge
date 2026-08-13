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

# Trackers running UNIT3D, i.e. every tracker whose uploader derives from
# Unit3dBaseUploader. UNIT3D's StoreTorrentRequest makes season_number and
# episode_number *required* on any TV-category upload, so these are the
# trackers a series release must have both values resolved for. Other series
# trackers treat them as optional (HDBits' tvdb_season/tvdb_episode) or don't
# use them at all (TorrentLeech, BeyondHD). ReelFliX is listed for
# completeness even though it is movie-only -- callers gate on MediaType.SERIES
# first, so its presence is a no-op.
UNIT3D_TRACKERS: frozenset[TrackerSelection] = frozenset(
    {
        TrackerSelection.AITHER,
        TrackerSelection.BLUTOPIA,
        TrackerSelection.DARK_PEERS,
        TrackerSelection.FEAR_NO_PEER,
        TrackerSelection.HUNO,
        TrackerSelection.LST,
        TrackerSelection.ONLY_ENCODES,
        TrackerSelection.REELFLIX,
        TrackerSelection.SEEDPOOL,
        TrackerSelection.SHARE_ISLAND,
        TrackerSelection.UPLOAD_CX,
        TrackerSelection.UTOPIA,
        TrackerSelection.YU_SCENE,
    }
)

# Trackers whose upload has no release-name field at all -- there is nothing
# for a title override to shape, so the Movies/Series Management settings
# pages don't offer one. PassThePopcorn derives its release from structured
# fields (resolution, codec, container, source, remaster_title) plus the name
# already inside the .torrent; see `ptp_uploader` in
# src/backend/trackers/passthepopcorn.py. This is about the upload payload,
# not media-type support, so it is independent of TRACKER_SUPPORTED_MEDIA
# above -- a tracker could in principle lack a title field for movies but
# have one for series, though none does today.
NO_RELEASE_NAME_FIELD: frozenset[TrackerSelection] = frozenset(
    {TrackerSelection.PASS_THE_POPCORN}
)
