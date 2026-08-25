"""Encode and decode a `ProcessingContext` as a JSON-safe document.

Only state a run cannot recompute is stored. Everything derived from config
or plugins -- the Jinja engine, flat filters, custom edition/cut info -- is
rebuilt by `create_processing_context` when a job is loaded, and the media
analysis cache is derived data that recomputes on first use.

`MediaInfo` objects are stored as their own XML dump rather than left to be
re-parsed from disk on load: `MediaInfo(xml)` rebuilds the object from the
string alone, so restoring a job neither re-runs libmediainfo over a
multi-gigabyte remux nor depends on the media file being reachable at that
moment. The file still has to exist before an upload actually runs; that is
checked separately.

Enums round-trip by member *name* rather than value. Some enums here are
built with `auto()`, whose integer values would shift if a member were ever
inserted above them, and a name also stays readable in the saved file.

The free-form fields plugins write to (`dynamic_data`, `plugin_data`, the
provider blobs) go through `values.encode_value`, which carries `Path`,
`MediaInfo`, enum, `tuple`, `set` and non-string-keyed dicts as typed
envelopes instead of dropping the key they sit in. See `values.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from enum import Enum
import json
from pathlib import Path
from typing import Any, TypeVar, cast

from pymediainfo import MediaInfo

from src.backend.jobs.values import (
    ENUM_REGISTRY,
    MediaInfoIndex,
    MediaInfoResolver,
    UnencodableValue,
    decode_value,
    encode_value,
    enum_from_name,
)
from src.backend.utils.media_info_utils import cache_full_mi_str, cache_mediainfo_obj
from src.context.processing_context import ProcessingContext
from src.enums.image_host import ImageHost, ImageSource
from src.enums.media_type import MediaType
from src.enums.series import EpisodeFormat
from src.enums.tmdb_genres import TMDBGenreIDsMovies, TMDBGenreIDsSeries
from src.enums.torrent_client import TorrentClientSelection
from src.enums.tracker_selection import TrackerSelection
from src.logger.nfo_forge_logger import LOG
from src.packages.custom_types import (
    ComparisonPair,
    ImageHostRef,
    ImageUploadData,
    ImageUploadFromTo,
)
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.plugins.api import MetadataMediaKind

EnumT = TypeVar("EnumT", bound=Enum)

AssetLoader = Callable[[str], "str | None"]
"""Reads one stored sidecar by filename, returning None when unavailable."""


class JobCodecError(Exception):
    """A job document could not be encoded or decoded."""


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------
def _path_to_str(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _str_to_path(value: Any) -> Path | None:
    return Path(value) if isinstance(value, str) and value else None


def _enum_name(member: Enum | None) -> str | None:
    return member.name if member is not None else None


def _enum_from_name(enum_cls: type[EnumT], name: Any) -> EnumT | None:
    """Resolve an enum member by name, tolerating a member that has since gone."""
    return cast("EnumT | None", enum_from_name(enum_cls, name))


# The instance id the 10 -> 11 config migration gives a profile's single
# pre-schema-11 Chevereto site. Job archives written before that hop name the
# kind with no instance, and resolve onto it.
_LEGACY_CHEVERETO_INSTANCE_ID = "1"


def _registered_enum(raw_name: Any, *allowed: type[Enum]) -> type[Enum] | None:
    """Look a stored enum class up, refusing one this field does not accept.

    `ENUM_REGISTRY` covers every enum a job can carry, so a field storing its
    own class name (a genre, an image destination) has to say which classes it
    will honour -- otherwise a hand-edited `job.json` could name any enum at
    all and be believed.
    """
    enum_cls = ENUM_REGISTRY.get(str(raw_name))
    return enum_cls if enum_cls in allowed else None


def _json_safe_mapping(
    mapping: dict[str, Any], label: str, index: MediaInfoIndex | None = None
) -> dict[str, Any]:
    """Keep only the entries of a free-form mapping that survive a save.

    `dynamic_data` and `plugin_data` are open to plugins, so their contents
    are not guaranteed to be serializable. `encode_value` carries the types a
    plugin actually tends to leave behind (see `values.py`); anything still
    outside that whitelist costs its own key rather than the whole job, and the
    drop is logged so it is not silent.
    """
    safe: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in mapping.items():
        try:
            encoded = encode_value(value, index=index)
            json.dumps(encoded)
        except (UnencodableValue, TypeError, ValueError):
            dropped.append(str(key))
            continue
        safe[str(key)] = encoded
    if dropped:
        LOG.warning(
            LOG.LOG_SOURCE.BE,
            f"Job save dropped non-serializable {label} key(s): {', '.join(dropped)}",
        )
    return safe


def _json_safe_value(
    value: Any, label: str, index: MediaInfoIndex | None = None
) -> Any:
    """Keep a free-form value only if it survives a save.

    The metadata providers hand back decoded JSON, so this normally passes
    untouched. A plugin is free to put anything in these fields, though, and one
    odd object should cost that field rather than the whole job.
    """
    try:
        encoded = encode_value(value, index=index)
        json.dumps(encoded)
    except (UnencodableValue, TypeError, ValueError):
        LOG.warning(LOG.LOG_SOURCE.BE, f"Job save dropped non-serializable {label}")
        return None
    return encoded


# --------------------------------------------------------------------------
# custom types
# --------------------------------------------------------------------------
def _image_upload_data_to_dict(data: ImageUploadData) -> dict[str, Any]:
    return {"url": data.url, "medium_url": data.medium_url}


def _image_upload_data_from_dict(document: Any) -> ImageUploadData | None:
    if not isinstance(document, dict):
        return None
    return ImageUploadData(
        url=document.get("url"), medium_url=document.get("medium_url")
    )


def _image_upload_from_to_to_dict(data: ImageUploadFromTo) -> dict[str, Any]:
    return {
        "img_from": _enum_name(data.img_from),
        **_image_destination_to_dict(data.img_to, _IMG_TO_KEYS),
    }


def _image_upload_from_to_from_dict(document: Any) -> ImageUploadFromTo | None:
    if not isinstance(document, dict):
        return None
    img_from = _enum_from_name(ImageSource, document.get("img_from"))
    img_to = _image_destination_from_dict(document, _IMG_TO_KEYS)
    if img_from is None or img_to is None:
        return None
    return ImageUploadFromTo(img_from=img_from, img_to=img_to)


def _indexed_images_from_dict(document: Any) -> dict[int, ImageUploadData]:
    """Rebuild one `{index: ImageUploadData}` map, skipping unusable entries.

    Indices are the screenshot's position in `loaded_images`, so they have to
    come back as the ints they went out as -- JSON object keys are strings.
    """
    if not isinstance(document, dict):
        return {}
    restored: dict[int, ImageUploadData] = {}
    for raw_index, data in document.items():
        restored_data = _image_upload_data_from_dict(data)
        if restored_data is None:
            continue
        try:
            restored[int(raw_index)] = restored_data
        except (TypeError, ValueError):
            continue
    return restored


def _comparison_pair_to_dict(pair: ComparisonPair | None) -> dict[str, Any] | None:
    if pair is None:
        return None
    return {
        "source": _path_to_str(pair.source),
        "media": _path_to_str(pair.media),
        "script": _path_to_str(pair.script),
    }


def _comparison_pair_from_dict(document: Any) -> ComparisonPair | None:
    if not isinstance(document, dict):
        return None
    source = _str_to_path(document.get("source"))
    media = _str_to_path(document.get("media"))
    if source is None or media is None:
        return None
    return ComparisonPair(
        source=source, media=media, script=_str_to_path(document.get("script"))
    )


# --------------------------------------------------------------------------
# media input
# --------------------------------------------------------------------------
def mediainfo_xml(path: Path) -> str:
    """Dump MediaInfo for `path` as XML that `MediaInfo(...)` can read back.

    `MediaInfo` does not retain the XML it was built from, so the dump is
    taken from the file again here. Parsing only reads container headers, so
    this stays cheap even for very large files. `legacy_stream_display`
    matches how the wizard parses media in the first place
    (`src/backend/media_input.py`), keeping the restored object identical to
    the one it replaces.

    The format matters: `MediaInfo.__init__` expects MediaInfo's *old* XML
    layout, which libmediainfo renamed to "OLDXML" in 17.10 -- asking a
    modern library for "XML" yields a document that parses into zero tracks
    rather than failing outright. Both names are tried, newest first, and the
    dump is only accepted once it has been proven to round-trip.
    """
    errors: list[str] = []
    for option in ("OLDXML", "XML"):
        try:
            xml = MediaInfo.parse(path, output=option, legacy_stream_display=True)
        except Exception as error:
            errors.append(f"{option}: {error}")
            continue
        if not isinstance(xml, str) or not xml.strip():
            errors.append(f"{option}: empty output")
            continue
        try:
            # every valid dump carries a General track, so its absence means
            # the document parsed but produced nothing usable
            if MediaInfo(xml).general_tracks:
                return xml
        except Exception as error:
            errors.append(f"{option}: not readable back ({error})")
            continue
        errors.append(f"{option}: produced no tracks when read back")
    raise JobCodecError(
        f"Could not capture round-trippable MediaInfo XML for '{path}' "
        f"({'; '.join(errors)})"
    )


def mediainfo_sources(context: ProcessingContext) -> dict[Path, MediaInfo]:
    """Every `MediaInfo` object this context can reach, keyed by media path.

    `file_list_mediainfo` is only the run's own view. A plugin that ingests a
    season pack keeps a `MediaInfo` per episode *source* on `dynamic_data`, and
    a metadata plugin can leave one on `plugin_data`; neither is in the file
    list, so capturing only that map wrote no dump for them and a resumed run
    found nothing to restore them from.

    An object already in the map keeps that path **by identity**. That is what
    survives `apply_rename_mapping` re-keying `file_list_mediainfo`
    (`src/payloads/media_inputs.py`) after a rename: the object's own
    `complete_name` still names where the file used to be, while the map holds
    where it now is, and the map is the one the rest of the run agrees with.

    Anything new derives its path from its General track's `complete_name`. An
    object that cannot say where it came from is skipped with a warning -- it
    has no path to file a dump under, and inventing one would put a sidecar
    somewhere nothing looks for it.
    """
    sources: dict[Path, MediaInfo] = dict(context.media_input.file_list_mediainfo)
    known: set[int] = {id(mi) for mi in sources.values()}

    for label, container in (
        ("dynamic_data", context.shared_data.dynamic_data),
        ("plugin_data", context.media_search.plugin_data),
        ("series_episode_map", context.media_input.series_episode_map),
    ):
        for mi in _walk_mediainfo(container, set()):
            if id(mi) in known:
                continue
            known.add(id(mi))
            path = _mediainfo_path(mi)
            if path is None:
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"Skipping a MediaInfo object on {label} that does not name "
                    "the file it came from; it cannot be saved with this job",
                )
                continue
            sources.setdefault(path, mi)
    return sources


def _walk_mediainfo(value: Any, seen: set[int]) -> Iterable[MediaInfo]:
    """Yield every `MediaInfo` reachable through nested containers."""
    if isinstance(value, MediaInfo):
        yield value
        return
    if not isinstance(value, (dict, list, tuple, set, frozenset)):
        return
    if id(value) in seen:
        return
    seen.add(id(value))
    entries = (
        [item for pair in value.items() for item in pair]
        if isinstance(value, dict)
        else value
    )
    for entry in entries:
        yield from _walk_mediainfo(entry, seen)


def _mediainfo_path(mi: MediaInfo) -> Path | None:
    """The media file a `MediaInfo` object says it was parsed from."""
    try:
        general = mi.general_tracks[0]
    except (AttributeError, IndexError):
        return None
    name = getattr(general, "complete_name", None)
    if not isinstance(name, str) or not name.strip():
        return None
    return Path(name)


def _media_input_to_dict(
    context: ProcessingContext,
    mediainfo_assets: dict[Path, dict[str, str]] | None,
    sources: dict[Path, MediaInfo],
    index: MediaInfoIndex,
) -> dict[str, Any]:
    payload = context.media_input

    # When the caller has written MediaInfo out as sidecar files, reference
    # those instead of inlining the dumps -- it keeps `job.json` small and
    # readable, and puts the OLDXML somewhere a user can actually look at.
    # Inlining remains the fallback so a context can still be serialized
    # standalone (tests, and any caller without a job directory).
    mediainfo_section: dict[str, Any] = {}
    if mediainfo_assets is None:
        inline: dict[str, str] = {}
        for path in sources:
            try:
                inline[str(path)] = mediainfo_xml(path)
            except Exception as error:
                raise JobCodecError(
                    f"Could not capture MediaInfo for '{path}': {error}"
                ) from error
        mediainfo_section["mediainfo_xml"] = inline
    else:
        mediainfo_section["mediainfo_assets"] = {
            str(path): dict(names) for path, names in mediainfo_assets.items()
        }

    series_episode_map: dict[str, Any] | None = None
    if payload.series_episode_map is not None:
        series_episode_map = {
            str(path): _json_safe_mapping(episode, "series_episode_map", index)
            for path, episode in payload.series_episode_map.items()
        }

    return {
        "input_path": _path_to_str(payload.input_path),
        "media_type": _enum_name(payload.media_type),
        "working_dir": _path_to_str(payload.working_dir),
        "file_list": [str(path) for path in payload.file_list],
        "input_kind": payload.input_kind,
        "content_size": payload.content_size,
        **mediainfo_section,
        "comparison_pair": _comparison_pair_to_dict(payload.comparison_pair),
        "series_episode_map": series_episode_map,
        "series_episode_format": _enum_name(payload.series_episode_format),
    }


def _restore_mediainfo(
    document: dict[str, Any],
    payload: MediaInputPayload,
    load_asset: AssetLoader | None,
) -> None:
    """Rebuild `MediaInfo` objects from whichever form the job stored.

    Either way the media file itself is never touched: `MediaInfo(xml)` parses
    the stored dump directly, which is the whole reason OLDXML is what gets
    saved.
    """

    def restore(raw_path: str, xml: str | None) -> None:
        if not xml or not xml.strip():
            return
        try:
            restored = MediaInfo(xml)
        except Exception as error:
            raise JobCodecError(
                f"Could not restore MediaInfo for '{raw_path}': {error}"
            ) from error
        payload.file_list_mediainfo[Path(raw_path)] = restored
        # `{media_info_short}` is built from a parsed object rather than from
        # a stored dump, so without this it would be the one token that still
        # reaches for the media file (`MinimalMediaInfo.get_minimal_mi_str`)
        cache_mediainfo_obj(Path(raw_path), restored)

    assets = document.get("mediainfo_assets")
    if isinstance(assets, dict) and load_asset is not None:
        for raw_path, names in assets.items():
            if not isinstance(names, dict):
                continue
            restore(raw_path, load_asset(str(names.get("xml") or "")))
            text_name = names.get("text")
            if isinstance(text_name, str) and text_name:
                text = load_asset(text_name)
                if text:
                    # what trackers are actually sent; cached so the upload
                    # path never re-reads the media to regenerate it
                    cache_full_mi_str(Path(raw_path), text)
        return

    inline = document.get("mediainfo_xml")
    if isinstance(inline, dict):
        for raw_path, xml in inline.items():
            restore(raw_path, xml if isinstance(xml, str) else None)


def _mediainfo_resolver(payload: MediaInputPayload) -> MediaInfoResolver:
    """Resolve a stored MediaInfo reference against what was just restored.

    `_restore_mediainfo` puts *every* captured asset into `file_list_mediainfo`,
    including dumps that only a plugin's state points at, so this is the single
    place a reference resolves from. `context_from_dict` decodes `media_input`
    first for exactly this reason -- do not reorder those sections.
    """

    def lookup(ref: str) -> MediaInfo | None:
        return payload.file_list_mediainfo.get(Path(ref))

    return MediaInfoResolver(lookup)


def _media_input_from_dict(
    document: dict[str, Any],
    context: ProcessingContext,
    load_asset: AssetLoader | None = None,
) -> None:
    payload = context.media_input
    payload.reset()

    payload.input_path = _str_to_path(document.get("input_path"))
    payload.media_type = _enum_from_name(MediaType, document.get("media_type"))
    payload.working_dir = _str_to_path(document.get("working_dir"))
    input_kind = document.get("input_kind")
    payload.input_kind = input_kind if input_kind in {"file", "directory"} else None
    content_size = document.get("content_size")
    payload.content_size = (
        content_size
        if isinstance(content_size, int) and not isinstance(content_size, bool)
        else None
    )

    file_list = document.get("file_list")
    if isinstance(file_list, list):
        payload.file_list.extend(
            Path(entry) for entry in file_list if isinstance(entry, str)
        )

    _restore_mediainfo(document, payload, load_asset)

    payload.comparison_pair = _comparison_pair_from_dict(
        document.get("comparison_pair")
    )

    series_episode_map = document.get("series_episode_map")
    if isinstance(series_episode_map, dict):
        resolver = _mediainfo_resolver(payload)
        payload.series_episode_map = {
            Path(raw_path): decode_value(episode, resolver=resolver)
            for raw_path, episode in series_episode_map.items()
            if isinstance(episode, dict)
        }

    episode_format = _enum_from_name(
        EpisodeFormat, document.get("series_episode_format")
    )
    if episode_format is not None:
        payload.series_episode_format = episode_format


# --------------------------------------------------------------------------
# media search
# --------------------------------------------------------------------------
def _media_search_to_dict(
    context: ProcessingContext, index: MediaInfoIndex
) -> dict[str, Any]:
    payload = context.media_search
    return {
        "media_type": _enum_name(payload.media_type),
        "imdb_id": payload.imdb_id,
        "tmdb_id": payload.tmdb_id,
        "tmdb_data": _json_safe_value(payload.tmdb_data, "tmdb_data", index),
        "tvdb_id": payload.tvdb_id,
        "tvdb_data": _json_safe_value(payload.tvdb_data, "tvdb_data", index),
        "anilist_id": payload.anilist_id,
        "anilist_data": _json_safe_value(payload.anilist_data, "anilist_data", index),
        "mal_id": payload.mal_id,
        "title": payload.title,
        "year": payload.year,
        "original_title": payload.original_title,
        "genres": [
            {"enum": type(genre).__name__, "name": genre.name}
            for genre in payload.genres
        ],
        "plot": payload.plot,
        "poster_url": payload.poster_url,
        "genre_names": list(payload.genre_names),
        "media_kind": _enum_name(payload.media_kind),
        "plugin_data": _json_safe_mapping(payload.plugin_data, "plugin_data", index),
    }


def _media_search_from_dict(
    document: dict[str, Any], context: ProcessingContext
) -> None:
    resolver = _mediainfo_resolver(context.media_input)

    # build into a scratch payload so `copy_from` can validate the result and
    # apply it without swapping the object the Jinja engine holds a reference to
    restored = MediaSearchPayload()
    restored.media_type = _enum_from_name(MediaType, document.get("media_type"))
    restored.imdb_id = document.get("imdb_id")
    restored.tmdb_id = document.get("tmdb_id")
    restored.tmdb_data = decode_value(document.get("tmdb_data"), resolver=resolver)
    restored.tvdb_id = document.get("tvdb_id")
    restored.tvdb_data = decode_value(document.get("tvdb_data"), resolver=resolver)
    restored.anilist_id = document.get("anilist_id")
    restored.anilist_data = decode_value(
        document.get("anilist_data"), resolver=resolver
    )
    restored.mal_id = document.get("mal_id")
    restored.title = document.get("title")
    restored.year = document.get("year")
    restored.original_title = document.get("original_title")
    restored.plot = document.get("plot")
    restored.poster_url = document.get("poster_url")

    genres = document.get("genres")
    if isinstance(genres, list):
        for entry in genres:
            if not isinstance(entry, dict):
                continue
            genre_cls = _registered_enum(
                entry.get("enum"), TMDBGenreIDsMovies, TMDBGenreIDsSeries
            )
            if genre_cls is None:
                continue
            genre = _enum_from_name(genre_cls, entry.get("name"))
            if genre is not None:
                restored.genres.append(genre)  # pyright: ignore[reportArgumentType]

    genre_names = document.get("genre_names")
    if isinstance(genre_names, list):
        restored.genre_names = tuple(
            name for name in genre_names if isinstance(name, str)
        )

    restored.media_kind = _enum_from_name(MetadataMediaKind, document.get("media_kind"))

    plugin_data = document.get("plugin_data")
    if isinstance(plugin_data, dict):
        restored.plugin_data.update(
            {
                key: decode_value(value, resolver=resolver)
                for key, value in plugin_data.items()
            }
        )

    context.media_search.copy_from(restored)


# --------------------------------------------------------------------------
# shared data
# --------------------------------------------------------------------------
# The three keys one destination occupies. `tracker_image_hosts` has always
# spelled them differently from the host-scoped maps, and both spellings are
# already on disk in saved jobs, so each keeps its own.
_DESTINATION_KEYS = ("name", "type", "instance")
_IMG_TO_KEYS = ("img_to", "img_to_type", "img_to_instance")


def _image_destination_to_dict(
    host: ImageHostRef | ImageSource,
    keys: tuple[str, str, str] = _DESTINATION_KEYS,
) -> dict[str, Any]:
    # a destination is an image host *or* an ImageSource; the member name alone
    # cannot say which, so the type travels with it. For a host the *kind* name
    # is not enough either -- Chevereto kinds hold several user-configured
    # instances -- so the instance id travels with it too.
    name_key, type_key, instance_key = keys
    if isinstance(host, ImageHostRef):
        return {
            name_key: host.kind.name,
            type_key: "ImageHostRef",
            instance_key: host.instance_id,
        }
    return {name_key: host.name, type_key: type(host).__name__}


def _image_destination_from_dict(
    document: Mapping[str, Any],
    keys: tuple[str, str, str] = _DESTINATION_KEYS,
) -> ImageHostRef | ImageSource | None:
    """Rebuild one destination, including archives written before schema 11.

    Those name a bare `ImageHost` member with no instance. The two Chevereto
    kinds map onto the single instance the 10 -> 11 config migration creates,
    so a job saved against the old single-slot Chevereto still points at the
    site that slot became; every other kind has no instance either way.
    """
    name_key, type_key, instance_key = keys
    raw_type = document.get(type_key)
    raw_name = document.get(name_key)
    if raw_type == "ImageHostRef":
        kind = _enum_from_name(ImageHost, raw_name)
        if kind is None:
            return None
        instance = document.get(instance_key)
        return ImageHostRef(
            kind=kind, instance_id=str(instance) if isinstance(instance, str) else ""
        )

    destination_cls = _registered_enum(raw_type, ImageHost, ImageSource)
    if destination_cls is None:
        return None
    member = _enum_from_name(destination_cls, raw_name)
    if isinstance(member, ImageHost):
        return ImageHostRef(
            kind=member,
            instance_id=_LEGACY_CHEVERETO_INSTANCE_ID
            if member in (ImageHost.CHEVERETO_V3, ImageHost.CHEVERETO_V4)
            else "",
        )
    if isinstance(member, ImageSource):
        return member
    return None


def _shared_data_to_dict(
    context: ProcessingContext,
    nfo_assets: dict[TrackerSelection, str] | None,
    index: MediaInfoIndex,
) -> dict[str, Any]:
    payload = context.shared_data
    return {
        "url_data": [_image_upload_data_to_dict(entry) for entry in payload.url_data],
        "selected_trackers": [
            _enum_name(tracker) for tracker in payload.selected_trackers
        ]
        if payload.selected_trackers is not None
        else None,
        "loaded_images": [str(path) for path in payload.loaded_images]
        if payload.loaded_images is not None
        else None,
        "generated_images": payload.generated_images,
        "is_comparison_images": payload.is_comparison_images,
        "dynamic_data": _json_safe_mapping(payload.dynamic_data, "dynamic_data", index),
        "release_notes": payload.release_notes,
        "tracker_image_hosts": {
            tracker.name: _image_upload_from_to_to_dict(image_host_data)
            for tracker, image_host_data in payload.tracker_image_hosts.items()
        },
        # what has already been uploaded, and where, so a resumed job does not
        # put the same screenshots on the host a second time
        "uploaded_images": {
            tracker.name: {
                str(index): _image_upload_data_to_dict(data)
                for index, data in images.items()
            }
            for tracker, images in payload.uploaded_images.items()
        },
        "uploaded_image_hosts": {
            tracker.name: _image_destination_to_dict(host)
            for tracker, host in payload.uploaded_image_hosts.items()
        },
        # The same URLs again, filed under the host that issued them rather
        # than the tracker that asked for them. Narrowing a job to fewer
        # trackers takes the per-tracker maps above with it, so an archive of a
        # fully successful run kept no URLs at all -- and a tracker added later
        # could not reuse another tracker's upload even when both point at the
        # same host. Host-scoped state answers both, and is never narrowed.
        "uploaded_images_by_host": [
            {
                **_image_destination_to_dict(host),
                "images": {
                    str(index): _image_upload_data_to_dict(data)
                    for index, data in images.items()
                },
            }
            for host, images in payload.uploaded_images_by_host.items()
        ],
        # Titles stay inline; NFO bodies are referenced by sidecar filename when
        # the caller captured them, the same way MediaInfo is handled, so a
        # multi-kilobyte NFO per tracker doesn't bloat job.json.
        "tracker_release_data": {
            tracker.name: {
                "title": release.get("title"),
                **(
                    {"nfo_asset": nfo_assets[tracker]}
                    if nfo_assets and tracker in nfo_assets
                    else {"nfo": release.get("nfo")}
                ),
            }
            for tracker, release in payload.tracker_release_data.items()
        },
        "prompt_token_answers": dict(payload.prompt_token_answers),
        "template_fingerprints": dict(payload.template_fingerprints),
    }


def _shared_data_from_dict(
    document: dict[str, Any],
    context: ProcessingContext,
    load_asset: AssetLoader | None = None,
) -> None:
    payload = context.shared_data
    payload.reset()

    url_data = document.get("url_data")
    if isinstance(url_data, list):
        for entry in url_data:
            restored_entry = _image_upload_data_from_dict(entry)
            if restored_entry is not None:
                payload.url_data.append(restored_entry)

    selected_trackers = document.get("selected_trackers")
    if isinstance(selected_trackers, list):
        payload.selected_trackers = [
            tracker
            for tracker in (
                _enum_from_name(TrackerSelection, name) for name in selected_trackers
            )
            if tracker is not None
        ]

    loaded_images = document.get("loaded_images")
    if isinstance(loaded_images, list):
        payload.loaded_images = [
            Path(entry) for entry in loaded_images if isinstance(entry, str)
        ]

    payload.generated_images = bool(document.get("generated_images"))
    payload.is_comparison_images = bool(document.get("is_comparison_images"))

    resolver = _mediainfo_resolver(context.media_input)

    dynamic_data = document.get("dynamic_data")
    if isinstance(dynamic_data, dict):
        payload.dynamic_data.update(
            {
                key: decode_value(value, resolver=resolver)
                for key, value in dynamic_data.items()
            }
        )

    release_notes = document.get("release_notes")
    payload.release_notes = release_notes if isinstance(release_notes, str) else None

    tracker_image_hosts = document.get("tracker_image_hosts")
    if isinstance(tracker_image_hosts, dict):
        for raw_tracker, raw_host in tracker_image_hosts.items():
            tracker = _enum_from_name(TrackerSelection, raw_tracker)
            image_host_data = _image_upload_from_to_from_dict(raw_host)
            if tracker is not None and image_host_data is not None:
                payload.tracker_image_hosts[tracker] = image_host_data

    uploaded_images = document.get("uploaded_images")
    if isinstance(uploaded_images, dict):
        for raw_tracker, images in uploaded_images.items():
            tracker = _enum_from_name(TrackerSelection, raw_tracker)
            if tracker is None:
                continue
            restored_images = _indexed_images_from_dict(images)
            if restored_images:
                payload.uploaded_images[tracker] = restored_images

    by_host = document.get("uploaded_images_by_host")
    if isinstance(by_host, list):
        for entry in by_host:
            if not isinstance(entry, dict):
                continue
            host = _image_destination_from_dict(entry)
            if host is None:
                continue
            restored_images = _indexed_images_from_dict(entry.get("images"))
            if restored_images:
                payload.uploaded_images_by_host[host] = restored_images

    uploaded_image_hosts = document.get("uploaded_image_hosts")
    if isinstance(uploaded_image_hosts, dict):
        for raw_tracker, raw_host in uploaded_image_hosts.items():
            tracker = _enum_from_name(TrackerSelection, raw_tracker)
            if tracker is None or not isinstance(raw_host, dict):
                continue
            host = _image_destination_from_dict(raw_host)
            if host is not None:
                payload.uploaded_image_hosts[tracker] = host

    release_data = document.get("tracker_release_data")
    if isinstance(release_data, dict):
        for raw_tracker, release in release_data.items():
            tracker = _enum_from_name(TrackerSelection, raw_tracker)
            if tracker is None or not isinstance(release, dict):
                continue
            nfo = release.get("nfo")
            asset_name = release.get("nfo_asset")
            if isinstance(asset_name, str) and asset_name and load_asset is not None:
                nfo = load_asset(asset_name)
            payload.tracker_release_data[tracker] = {
                "title": release.get("title"),
                "nfo": nfo,
            }

    prompt_token_answers = document.get("prompt_token_answers")
    if isinstance(prompt_token_answers, dict):
        payload.prompt_token_answers.update(
            {
                str(token): str(answer)
                for token, answer in prompt_token_answers.items()
                if isinstance(answer, str)
            }
        )

    template_fingerprints = document.get("template_fingerprints")
    if isinstance(template_fingerprints, dict):
        payload.template_fingerprints.update(
            {
                str(name): str(digest)
                for name, digest in template_fingerprints.items()
                if isinstance(digest, str)
            }
        )


# --------------------------------------------------------------------------
# run options
#
# `ProcessingContext.generated_torrents` and `.uploaded_images` are pointedly
# absent here. Nothing in `process_trackers()` or the image backend ever writes
# to them -- they are unused fields -- so serializing them only ever stored two
# empty dicts and implied a job carried per-tracker output state it does not.
# --------------------------------------------------------------------------
def _outputs_to_dict(context: ProcessingContext) -> dict[str, Any]:
    return {
        "torrent_client_options": {
            "save_path_overrides": {
                client.name: path
                for client, path in (
                    context.torrent_client_options.save_path_overrides.items()
                )
            }
        },
    }


def _outputs_from_dict(document: dict[str, Any], context: ProcessingContext) -> None:
    context.torrent_client_options.save_path_overrides.clear()
    client_options = document.get("torrent_client_options")
    if isinstance(client_options, dict):
        overrides = client_options.get("save_path_overrides")
        if isinstance(overrides, dict):
            for raw_client, path in overrides.items():
                client = _enum_from_name(TorrentClientSelection, raw_client)
                if client is not None and isinstance(path, str):
                    context.torrent_client_options.save_path_overrides[client] = path


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def context_to_dict(
    context: ProcessingContext,
    mediainfo_assets: dict[Path, dict[str, str]] | None = None,
    nfo_assets: dict[TrackerSelection, str] | None = None,
) -> dict[str, Any]:
    """Encode the resumable parts of `context` as a JSON-safe document.

    Pass `mediainfo_assets` (from `assets.capture_mediainfo`) and `nfo_assets`
    (from `assets.capture_nfos`) to reference sidecar files instead of inlining
    those dumps.
    """
    # One index for the whole document: a `MediaInfo` (or one of its `Track`s)
    # that a plugin left on `dynamic_data` is stored as a reference to the path
    # whose dump was captured, so encoding has to agree with what was written.
    sources = mediainfo_sources(context)
    index = MediaInfoIndex(sources)

    return {
        "media_input": _media_input_to_dict(context, mediainfo_assets, sources, index),
        "media_search": _media_search_to_dict(context, index),
        "shared_data": _shared_data_to_dict(context, nfo_assets, index),
        **_outputs_to_dict(context),
    }


def context_from_dict(
    document: dict[str, Any],
    context: ProcessingContext,
    load_asset: AssetLoader | None = None,
) -> None:
    """Restore a saved document into an already-built `context`, in place.

    The context must come from `create_processing_context` so the Jinja
    engine, filters and plugin-derived data are already wired up. The payload
    objects are mutated rather than replaced because
    `ProcessingContext.__post_init__` registers them as Jinja globals --
    rebinding the attributes would leave the engine pointing at the old
    payloads.
    """
    for section in ("media_input", "media_search", "shared_data"):
        if not isinstance(document.get(section), dict):
            raise JobCodecError(f"Job document is missing its '{section}' section")

    _media_input_from_dict(document["media_input"], context, load_asset)
    _media_search_from_dict(document["media_search"], context)
    _shared_data_from_dict(document["shared_data"], context, load_asset)
    _outputs_from_dict(document, context)


_PER_TRACKER_KEYS = (
    "tracker_image_hosts",
    "uploaded_images",
    "uploaded_image_hosts",
    "tracker_release_data",
)
"""Every `shared_data` map keyed by tracker name.

`filter_context_document` narrows all of these together, so a per-tracker map
added to `SharedPayload` has to be listed here too. Leaving one out means a
dropped tracker's state survives the narrowing as an orphan, and a retained
one's state is only half kept.

Note what is deliberately absent: `uploaded_images_by_host` is keyed by image
host, not by tracker, and narrowing it is what left a fully successful run's
archive with no image URLs at all.
"""


def filter_context_document(
    document: dict[str, Any],
    keep_trackers: Iterable[TrackerSelection],
    *,
    retain_data_for: Iterable[TrackerSelection] = (),
) -> dict[str, Any]:
    """Return a copy of `document` narrowed to `keep_trackers`.

    This is what makes saving a job partway through a run safe. Rather than
    teaching resume to skip trackers that already uploaded -- which would put a
    duplicate upload one bug away -- the deferred job is written with only the
    trackers that still need uploading. The result is structurally identical to
    a job saved before any upload was attempted, so nothing downstream needs to
    know it came from a partial run.

    `retain_data_for` names trackers that must **not** run but whose prepared
    work is worth keeping -- an upload nobody could confirm either way. They
    stay out of `selected_trackers`, so no resume can send to them, while their
    title, NFO reference and image state stay in the document. That is what
    lets "the upload never landed after all" put a tracker back into play with
    the NFO it was prepared with, instead of offering a resolution the data can
    no longer support. `store.prune_unreferenced_nfos` leaves their sidecars
    alone for the same reason: `tracker_release_data` still points at them.
    """
    keep = list(keep_trackers)
    keep_names = {tracker.name for tracker in keep}
    data_names = keep_names | {tracker.name for tracker in retain_data_for}
    filtered = dict(document)

    shared_data = filtered.get("shared_data")
    if not isinstance(shared_data, dict):
        return filtered

    shared_copy = dict(shared_data)

    selected = shared_copy.get("selected_trackers")
    if isinstance(selected, list):
        shared_copy["selected_trackers"] = [
            name for name in selected if name in keep_names
        ]

    # every per-tracker map has to be narrowed together, or a dropped tracker
    # leaves its uploaded-image URLs and frozen NFO behind as confusing orphans
    for key in _PER_TRACKER_KEYS:
        value = shared_copy.get(key)
        if isinstance(value, dict):
            shared_copy[key] = {
                name: entry for name, entry in value.items() if name in data_names
            }

    # A tracker being kept is one that still has to upload, so it has to be
    # selectable -- and it is not always already selected. `_run_outcomes`
    # covers only the run that just ended, so a tracker left pending by an
    # *earlier* run reaches here holding a prepared title and NFO while being
    # absent from this run's `selected_trackers`. Narrowing alone left it in
    # the document but unrunnable: the picker showed it, and resuming built no
    # row for it.
    _select_prepared(shared_copy, keep)

    filtered["shared_data"] = shared_copy
    return filtered


def _select_prepared(
    shared: dict[str, Any], trackers: Iterable[TrackerSelection]
) -> list[str]:
    """Add `trackers` to `selected_trackers`, but only where they can run.

    A tracker with no `tracker_release_data` is left out: its title and NFO are
    gone, so selecting it would produce a job that reports itself prepared and
    then uploads whatever a fresh render produces, which is not what the user
    reviewed. A job with no release data at all is not prepared in the first
    place, and its selection is left exactly as it is.
    """
    release_data = shared.get("tracker_release_data")
    if not isinstance(release_data, dict):
        return []
    selected = shared.get("selected_trackers")
    names = list(selected) if isinstance(selected, list) else []
    refused: list[str] = []
    for tracker in trackers:
        if tracker.name in release_data:
            if tracker.name not in names:
                names.append(tracker.name)
        elif release_data:
            refused.append(str(tracker))
    shared["selected_trackers"] = names
    return refused


def reselect_trackers(
    document: dict[str, Any], trackers: Iterable[TrackerSelection]
) -> dict[str, Any]:
    """Return a copy of `document` with `trackers` runnable again.

    The counterpart to `filter_context_document(retain_data_for=...)`: a
    tracker whose upload could not be confirmed was held back from
    `selected_trackers` but kept everything else, and resolving that
    uncertainty as "it never landed" puts it back.

    A tracker with no `tracker_release_data` is refused rather than re-added.
    Its title and NFO are gone, so selecting it would produce a job that claims
    to be prepared and then uploads whatever a fresh render produces -- which
    is not what the user reviewed.
    """
    filtered = dict(document)
    shared_data = filtered.get("shared_data")
    if not isinstance(shared_data, dict):
        return filtered

    shared_copy = dict(shared_data)
    if not isinstance(shared_copy.get("tracker_release_data"), dict):
        return filtered

    for name in _select_prepared(shared_copy, trackers):
        LOG.warning(
            LOG.LOG_SOURCE.BE,
            f"Not restoring {name} to a saved job: it no longer carries a "
            "title or NFO for that tracker",
        )
    filtered["shared_data"] = shared_copy
    return filtered
