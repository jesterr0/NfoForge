"""Typed envelopes for the free-form state a run leaves on the context.

`shared_data.dynamic_data`, `media_search.plugin_data` and the metadata
providers' blobs are open to plugins, so what lands in them is whatever a
plugin found useful -- commonly a `Path`, a `MediaInfo`, an enum member, or a
dict keyed by any of those. Plain `json.dumps` refuses all of them, and the
saver's response was to drop the offending top-level key: a single `Path`
inside a nested mapping cost the whole mapping, silently, at save time.

The types below therefore round-trip through typed envelopes rather than being
dropped:

    Path        {"__nf__": "path", "v": "..."}
    MediaInfo   {"__nf__": "mediainfo", "ref": "<canonical media path>"}
    Track       {"__nf__": "track", "ref": "<canonical media path>", "i": 3}
    Enum        {"__nf__": "enum", "cls": "ImageHost", "name": "PIXHOST"}
    tuple/set   {"__nf__": "tuple"|"set", "v": [...]}
    dict        {"__nf__": "map", "items": [[k, v], ...]}   (non-string keys)

Plain JSON scalars, lists and all-string-keyed dicts pass through unchanged, so
documents written before any of this keep exactly the shape they had.

The promise is a *documented set of types*, not "anything a plugin holds": a
socket or a Qt widget cannot be written to a file and read back, so anything
outside the whitelist raises `UnencodableValue` and the caller drops that key
with a warning, as it always did.

`MediaInfo` and `Track` are the types not stored inline. The OLDXML dump is
already captured once per media file as a sidecar
(`assets.capture_mediainfo`), so an envelope carries a reference to the path
that dump belongs to -- plus, for a `Track`, its position in that file's track
list -- and the loader hands back the object rebuilt from it. That keeps one
copy of a multi-hundred-kilobyte dump instead of one per plugin that held a
reference, and a restored `Track` is genuinely the restored `MediaInfo`'s own
track rather than a detached copy of it.

A reference that cannot be built -- a `Track` belonging to a file this job
does not carry, which is what a hand-corrected audio mapping holds -- is
stored with a null `ref` and comes back as `None`, logged at both ends. That
is deliberately not `UnencodableValue`: the type is one we understand, so it
costs itself rather than the whole mapping it sits in.

Qt-free, like the rest of the package.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import Enum
from pathlib import Path, PurePath
from typing import Any

from pymediainfo import MediaInfo, Track

from src.enums.audio_channels import AudioChannels
from src.enums.audio_formats import AudioFormats
from src.enums.cropping import Cropping
from src.enums.image_host import ImageHost, ImageSource
from src.enums.image_plugin import ImagePlugin
from src.enums.indexer import Indexer
from src.enums.media_search_mode import MediaSearchMode
from src.enums.media_type import MediaType
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.rename import QualitySelection
from src.enums.screen_shot_mode import ScreenShotMode
from src.enums.series import EpisodeFormat
from src.enums.subtitles import SubtitleAlignment
from src.enums.theme import NfoForgeTheme
from src.enums.tmdb_genres import TMDBGenreIDsMovies, TMDBGenreIDsSeries
from src.enums.token_replacer import ColonReplace, SharedWithType, UnfilledTokenRemoval
from src.enums.torrent_client import QBittorrentSavePathMode, TorrentClientSelection
from src.enums.tracker_selection import TrackerSelection
from src.enums.tvdb_season_type import TVDBSeasonType
from src.enums.url_type import URLType
from src.logger.nfo_forge_logger import LOG
from src.plugins.api import MetadataMediaKind, PostUploadOutcome, PreUploadDecision

__all__ = [
    "ENUM_REGISTRY",
    "ENVELOPE_KEY",
    "MediaInfoIndex",
    "MediaInfoLookup",
    "MediaInfoResolver",
    "UnencodableValue",
    "decode_value",
    "encode_value",
    "enum_from_name",
]

ENVELOPE_KEY = "__nf__"
"""Marks a dict as a typed envelope rather than data of the job's own."""

MediaInfoLookup = Callable[[str], "MediaInfo | None"]
"""Resolves a stored reference back to the restored `MediaInfo` object."""

ENUM_REGISTRY: dict[str, type[Enum]] = {
    enum_cls.__name__: enum_cls
    for enum_cls in (
        AudioChannels,
        AudioFormats,
        ColonReplace,
        Cropping,
        EpisodeFormat,
        ImageHost,
        ImagePlugin,
        ImageSource,
        Indexer,
        MediaSearchMode,
        MediaType,
        MetadataMediaKind,
        MultiEpisodeStyle,
        NfoForgeTheme,
        PostUploadOutcome,
        PreUploadDecision,
        QBittorrentSavePathMode,
        QualitySelection,
        ScreenShotMode,
        SharedWithType,
        SubtitleAlignment,
        TMDBGenreIDsMovies,
        TMDBGenreIDsSeries,
        TVDBSeasonType,
        TorrentClientSelection,
        TrackerSelection,
        URLType,
        UnfilledTokenRemoval,
    )
}
"""The one place an enum name is resolved back to its class.

Every enum that reaches a saved job goes through here, so a member is stored by
*name* once and read back the same way wherever it appears -- a genre, an image
destination, or something a plugin left on `dynamic_data`.

Deliberately explicit rather than discovered by walking `src.enums`: a frozen
build has no package directory to walk, and a registry that silently comes back
empty there would turn every enum in every saved job into `None`.

Members are keyed by class name, so an enum this build has never heard of --
one a plugin defines, or one from a newer release -- resolves to `None` and is
logged, the same tolerance `enum_from_name` applies to a retired member.
"""


class UnencodableValue(Exception):
    """A value holds something no job file can carry."""


class MediaInfoIndex:
    """Which stored dump each live `MediaInfo`/`Track` object belongs to.

    Keyed by `id`: `MediaInfo` and `Track` have no equality of their own, and
    the same file parsed twice yields two unrelated objects that must not be
    treated as one. The objects here are the ones the run is holding, so
    identity is exactly the question being asked.
    """

    __slots__ = ("_media_info", "_tracks")

    def __init__(self, sources: Mapping[Path, MediaInfo]) -> None:
        self._media_info: dict[int, str] = {}
        self._tracks: dict[int, tuple[str, int]] = {}
        for path, media_info in sources.items():
            reference = str(path)
            self._media_info[id(media_info)] = reference
            for position, track in enumerate(getattr(media_info, "tracks", ()) or ()):
                self._tracks[id(track)] = (reference, position)

    def ref(self, media_info: MediaInfo) -> str | None:
        return self._media_info.get(id(media_info))

    def track_ref(self, track: Track) -> tuple[str, int] | None:
        return self._tracks.get(id(track))


class MediaInfoResolver:
    """The read side of `MediaInfoIndex`, over whatever a load restored."""

    __slots__ = ("_lookup",)

    def __init__(self, lookup: MediaInfoLookup) -> None:
        self._lookup = lookup

    def media_info(self, reference: str) -> MediaInfo | None:
        return self._lookup(reference)

    def track(self, reference: str, position: int) -> Track | None:
        media_info = self._lookup(reference)
        tracks = getattr(media_info, "tracks", None) if media_info else None
        if not tracks or not 0 <= position < len(tracks):
            return None
        return tracks[position]


def enum_from_name(enum_cls: type[Enum], name: Any) -> Enum | None:
    """Resolve an enum member by name, tolerating a member that has since gone.

    A saved job outliving an enum member (a retired tracker, say) should not
    make the whole job unreadable, so an unknown name degrades to `None` and
    is logged rather than raising.
    """
    if not isinstance(name, str) or not name:
        return None
    try:
        return enum_cls[name]
    except KeyError:
        LOG.warning(
            LOG.LOG_SOURCE.BE,
            f"Saved job references unknown {enum_cls.__name__} member '{name}'; "
            "dropping it",
        )
        return None


_EMPTY_INDEX = MediaInfoIndex({})


# --------------------------------------------------------------------------
# encoding
# --------------------------------------------------------------------------
def encode_value(value: Any, *, index: MediaInfoIndex | None = None) -> Any:
    """Return `value` in a form `json.dumps` accepts, keeping its type.

    Raises `UnencodableValue` for anything outside the whitelist, which the
    caller turns into "drop this one key and warn" rather than a failed save.
    """
    return _encode(value, index or _EMPTY_INDEX, set())


def _encode(value: Any, index: MediaInfoIndex, seen: set[int]) -> Any:
    # Enum first: an `IntEnum` is an `int` and a `StrEnum` is a `str`, so a
    # scalar check would swallow the member and store a bare value that comes
    # back as the wrong type.
    if isinstance(value, Enum):
        return {
            ENVELOPE_KEY: "enum",
            "cls": type(value).__name__,
            "name": value.name,
        }

    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, PurePath):
        return {ENVELOPE_KEY: "path", "v": str(value)}

    if isinstance(value, MediaInfo):
        reference = index.ref(value)
        if reference is None:
            # Reachable only when `mediainfo_sources` could not work out which
            # file the object came from, which it already warned about.
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                "Job save is dropping a MediaInfo object with no stored dump "
                "to reference",
            )
        return {ENVELOPE_KEY: "mediainfo", "ref": reference}

    # Before the container checks: a `Track` is not a container, but it does
    # come from one -- `MediaInfo.tracks` -- and is stored as a position in
    # that list rather than as a copy of the track's own data.
    if isinstance(value, Track):
        located = index.track_ref(value)
        if located is None:
            # A hand-corrected audio mapping holds a track taken from a file
            # that is not this release's source, so the job carries no dump it
            # could be read back out of. `Track` has no back-reference to its
            # `MediaInfo`, so there is nothing further to look up.
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                "Job save is dropping a MediaInfo track that belongs to a file "
                "this job does not carry",
            )
            return {ENVELOPE_KEY: "track", "ref": None, "i": -1}
        reference, position = located
        return {ENVELOPE_KEY: "track", "ref": reference, "i": position}

    if isinstance(value, (list, tuple, set, frozenset, dict)):
        # a container that reaches itself would recurse until the stack ran
        # out, which reads as a crash rather than as one unsaveable key
        if id(value) in seen:
            raise UnencodableValue("a container that contains itself")
        seen = seen | {id(value)}

    if isinstance(value, list):
        return [_encode(entry, index, seen) for entry in value]

    if isinstance(value, tuple):
        return {
            ENVELOPE_KEY: "tuple",
            "v": [_encode(entry, index, seen) for entry in value],
        }

    if isinstance(value, (set, frozenset)):
        return {
            ENVELOPE_KEY: "set",
            "v": [_encode(entry, index, seen) for entry in _ordered(value)],
        }

    if isinstance(value, dict):
        if all(
            isinstance(key, str) and key != ENVELOPE_KEY and not isinstance(key, Enum)
            for key in value
        ):
            return {key: _encode(entry, index, seen) for key, entry in value.items()}
        return {
            ENVELOPE_KEY: "map",
            "items": [
                [_encode(key, index, seen), _encode(entry, index, seen)]
                for key, entry in value.items()
            ],
        }

    raise UnencodableValue(f"a value of type {type(value).__name__}")


def _ordered(values: set[Any] | frozenset[Any]) -> list[Any]:
    """A set in a stable order where one exists, so saves stop churning.

    Set iteration order varies between runs, which would rewrite `job.json`
    with a different ordering every save. Mixed-type sets have no total order,
    so those fall back to whatever order iteration gives.
    """
    try:
        return sorted(values)
    except TypeError:
        return list(values)


# --------------------------------------------------------------------------
# decoding
# --------------------------------------------------------------------------
def decode_value(document: Any, *, resolver: MediaInfoResolver | None = None) -> Any:
    """Rebuild what `encode_value` stored, restoring each value's own type.

    Never raises. A reference that no longer resolves -- a retired enum member,
    a MediaInfo dump the job no longer carries -- degrades to `None` and is
    logged, so one lost value costs that value rather than the job.
    """
    return _decode(document, resolver or MediaInfoResolver(lambda _ref: None))


def _decode(document: Any, resolver: MediaInfoResolver) -> Any:
    if isinstance(document, list):
        return [_decode(entry, resolver) for entry in document]

    if not isinstance(document, dict):
        return document

    kind = document.get(ENVELOPE_KEY)
    if kind is None:
        return {key: _decode(entry, resolver) for key, entry in document.items()}

    if kind == "path":
        raw = document.get("v")
        return Path(raw) if isinstance(raw, str) and raw else None

    if kind == "mediainfo":
        ref = document.get("ref")
        media_info = resolver.media_info(ref) if isinstance(ref, str) and ref else None
        if media_info is None:
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Saved job has no stored MediaInfo for '{ref}'; dropping it",
            )
        return media_info

    if kind == "track":
        ref, position = document.get("ref"), document.get("i")
        track = (
            resolver.track(ref, position)
            if isinstance(ref, str) and ref and isinstance(position, int)
            else None
        )
        if track is None:
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Saved job has no stored MediaInfo track {position} for "
                f"'{ref}'; dropping it",
            )
        return track

    if kind == "enum":
        enum_cls = ENUM_REGISTRY.get(str(document.get("cls")))
        if enum_cls is None:
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Saved job references unknown enum '{document.get('cls')}'; "
                "dropping it",
            )
            return None
        return enum_from_name(enum_cls, document.get("name"))

    if kind in {"tuple", "set"}:
        raw = document.get("v")
        entries = (
            [_decode(entry, resolver) for entry in raw] if isinstance(raw, list) else []
        )
        if kind == "tuple":
            return tuple(entries)
        return {entry for entry in entries if _hashable(entry)}

    if kind == "map":
        raw = document.get("items")
        restored: dict[Any, Any] = {}
        if isinstance(raw, list):
            for pair in raw:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    continue
                key = _decode(pair[0], resolver)
                if not _hashable(key):
                    LOG.warning(
                        LOG.LOG_SOURCE.BE,
                        f"Saved job has an unusable mapping key {key!r}; dropping it",
                    )
                    continue
                restored[key] = _decode(pair[1], resolver)
        return restored

    LOG.warning(
        LOG.LOG_SOURCE.BE,
        f"Saved job holds a value of unknown kind '{kind}'; dropping it",
    )
    return None


def _hashable(value: Any) -> bool:
    try:
        hash(value)
    except TypeError:
        return False
    return True
