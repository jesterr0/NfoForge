from nfoforge.core.disc.model import DiscType
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.tracker_selection import TrackerSelection

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


_ALL_DISCS = frozenset({DiscType.BDMV, DiscType.DVD})
_BLURAY_ONLY = frozenset({DiscType.BDMV})
_NO_DISCS: frozenset[DiscType] = frozenset()

# Which full discs each tracker takes. Every TrackerSelection needs a row, as
# above. BeyondHD, LST, ReelFliX, PTP and TorrentLeech take both; HDBits and
# Blutopia are HD-only, so Blu-ray only. Every other tracker is blocked until
# its rules are checked: see DISCS_UNCONFIRMED.
TRACKER_SUPPORTED_DISCS: dict[TrackerSelection, frozenset[DiscType]] = {
    TrackerSelection.TORRENT_LEECH: _ALL_DISCS,
    TrackerSelection.BEYOND_HD: _ALL_DISCS,
    TrackerSelection.PASS_THE_POPCORN: _ALL_DISCS,
    TrackerSelection.REELFLIX: _ALL_DISCS,
    TrackerSelection.AITHER: _NO_DISCS,
    TrackerSelection.HUNO: _NO_DISCS,
    TrackerSelection.LST: _ALL_DISCS,
    TrackerSelection.DARK_PEERS: _NO_DISCS,
    TrackerSelection.SHARE_ISLAND: _NO_DISCS,
    TrackerSelection.UPLOAD_CX: _NO_DISCS,
    TrackerSelection.ONLY_ENCODES: _NO_DISCS,
    TrackerSelection.HDB: _BLURAY_ONLY,
    TrackerSelection.BLUTOPIA: _BLURAY_ONLY,
    TrackerSelection.SEEDPOOL: _NO_DISCS,
    TrackerSelection.UTOPIA: _NO_DISCS,
    TrackerSelection.YU_SCENE: _NO_DISCS,
    TrackerSelection.FEAR_NO_PEER: _NO_DISCS,
}

# Trackers whose full-disc rules are not checked yet, so NfoForge sends them
# no disc. Moving one out of here means giving it its disc types above.
DISCS_UNCONFIRMED: frozenset[TrackerSelection] = frozenset(
    {
        TrackerSelection.AITHER,
        TrackerSelection.DARK_PEERS,
        TrackerSelection.FEAR_NO_PEER,
        TrackerSelection.HUNO,
        TrackerSelection.SEEDPOOL,
        TrackerSelection.SHARE_ISLAND,
        TrackerSelection.UPLOAD_CX,
        TrackerSelection.UTOPIA,
        TrackerSelection.YU_SCENE,
    }
)


# Trackers that take a full disc as one `.iso` image, of any disc type they
# take at all. PTP lists ISO as a container. No other tracker is checked yet.
TRACKER_SUPPORTED_IMAGES: frozenset[TrackerSelection] = frozenset(
    {TrackerSelection.PASS_THE_POPCORN}
)


def supports_disc(
    tracker: TrackerSelection, disc_type: DiscType, *, image: bool = False
) -> bool:
    """Return whether ``tracker`` takes a full disc of ``disc_type``.

    ``image`` is a disc uploaded as its `.iso` rather than its folder.
    """
    if image and tracker not in TRACKER_SUPPORTED_IMAGES:
        return False
    return disc_type in TRACKER_SUPPORTED_DISCS[tracker]


DISC_KIND_NAMES = {DiscType.BDMV: "Blu-ray", DiscType.DVD: "DVD"}


def unsupported_trackers(
    media_type: MediaType | None,
    disc_type: DiscType | None = None,
    *,
    image: bool = False,
) -> dict[TrackerSelection, str]:
    """Every tracker that cannot take this release, with the reason why."""
    reasons: dict[TrackerSelection, str] = {}
    for tracker in TRACKER_SUPPORTED_MEDIA:
        if media_type is not None and not supports_media(tracker, media_type):
            noun = "series" if media_type is MediaType.SERIES else "movie"
            reasons[tracker] = (
                f"{tracker} does not support {noun} uploads in NfoForge yet."
            )
        elif disc_type is not None and not supports_disc(
            tracker, disc_type, image=image
        ):
            reasons[tracker] = disc_refusal(tracker, disc_type, image=image)
    return reasons


def disc_refusal(
    tracker: TrackerSelection, disc_type: DiscType, *, image: bool = False
) -> str:
    """Why `tracker` is not sent a full disc of `disc_type`."""
    kind = DISC_KIND_NAMES[disc_type]
    if tracker in DISCS_UNCONFIRMED:
        return (
            f"Full {kind} discs are not enabled for {tracker} yet: its rules for "
            "full discs have not been checked."
        )
    if disc_type not in TRACKER_SUPPORTED_DISCS[tracker]:
        return f"{tracker} does not accept a full {kind} disc."
    if image:
        return (
            f"Disc images (.iso) are not enabled for {tracker} yet: whether it "
            "takes one has not been checked. Upload the disc's folder instead."
        )
    return f"{tracker} does not accept a full {kind} disc."


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

# Whether a tracker's upload has a release-name field at all is a title rule,
# so it lives on that tracker's entry rather than here beside the media-type
# support tables, which answer a different question -- see
# `accepts_a_release_name` in `title_rules.py`.
