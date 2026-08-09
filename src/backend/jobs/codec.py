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
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from enum import Enum
import json
from pathlib import Path
from typing import Any, TypeVar

from pymediainfo import MediaInfo

from src.backend.utils.media_info_utils import cache_full_mi_str
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
    ImageUploadData,
    ImageUploadFromTo,
)
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.plugins.api import MetadataMediaKind

EnumT = TypeVar("EnumT", bound=Enum)

AssetLoader = Callable[[str], "str | None"]
"""Reads one stored sidecar by filename, returning None when unavailable."""

_GENRE_ENUMS: dict[str, type[Enum]] = {
    "TMDBGenreIDsMovies": TMDBGenreIDsMovies,
    "TMDBGenreIDsSeries": TMDBGenreIDsSeries,
}

_IMAGE_DESTINATION_ENUMS: dict[str, type[Enum]] = {
    "ImageHost": ImageHost,
    "ImageSource": ImageSource,
}


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


def _json_safe_mapping(mapping: dict[str, Any], label: str) -> dict[str, Any]:
    """Keep only the entries of a free-form mapping that survive JSON.

    `dynamic_data` and `plugin_data` are open to plugins, so their contents
    are not guaranteed to be serializable. Dropping the offending keys keeps
    the rest of the job saveable instead of failing the whole save, and the
    drop is logged so it is not silent.
    """
    safe: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in mapping.items():
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            dropped.append(str(key))
            continue
        safe[str(key)] = value
    if dropped:
        LOG.warning(
            LOG.LOG_SOURCE.BE,
            f"Job save dropped non-serializable {label} key(s): {', '.join(dropped)}",
        )
    return safe


def _json_safe_value(value: Any, label: str) -> Any:
    """Keep a free-form value only if it survives JSON.

    The metadata providers hand back decoded JSON, so this normally passes
    untouched. A plugin is free to put anything in these fields, though, and one
    odd object should cost that field rather than the whole job.
    """
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        LOG.warning(LOG.LOG_SOURCE.BE, f"Job save dropped non-serializable {label}")
        return None
    return value


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
        "img_to": _enum_name(data.img_to),
        # `img_to` is an ImageHost *or* an ImageSource; the member name alone
        # cannot say which, so the type travels with it
        "img_to_type": type(data.img_to).__name__,
    }


def _image_upload_from_to_from_dict(document: Any) -> ImageUploadFromTo | None:
    if not isinstance(document, dict):
        return None
    img_from = _enum_from_name(ImageSource, document.get("img_from"))
    destination_cls = _IMAGE_DESTINATION_ENUMS.get(str(document.get("img_to_type")))
    if img_from is None or destination_cls is None:
        return None
    img_to = _enum_from_name(destination_cls, document.get("img_to"))
    if img_to is None:
        return None
    return ImageUploadFromTo(img_from=img_from, img_to=img_to)  # pyright: ignore[reportArgumentType]


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


def _media_input_to_dict(
    context: ProcessingContext,
    mediainfo_assets: dict[Path, dict[str, str]] | None,
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
        for path in payload.file_list_mediainfo:
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
            str(path): _json_safe_mapping(episode, "series_episode_map")
            for path, episode in payload.series_episode_map.items()
        }

    return {
        "input_path": _path_to_str(payload.input_path),
        "media_type": _enum_name(payload.media_type),
        "working_dir": _path_to_str(payload.working_dir),
        "file_list": [str(path) for path in payload.file_list],
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
            payload.file_list_mediainfo[Path(raw_path)] = MediaInfo(xml)
        except Exception as error:
            raise JobCodecError(
                f"Could not restore MediaInfo for '{raw_path}': {error}"
            ) from error

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
        payload.series_episode_map = {
            Path(raw_path): episode
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
def _media_search_to_dict(context: ProcessingContext) -> dict[str, Any]:
    payload = context.media_search
    return {
        "media_type": _enum_name(payload.media_type),
        "imdb_id": payload.imdb_id,
        "tmdb_id": payload.tmdb_id,
        "tmdb_data": _json_safe_value(payload.tmdb_data, "tmdb_data"),
        "tvdb_id": payload.tvdb_id,
        "tvdb_data": _json_safe_value(payload.tvdb_data, "tvdb_data"),
        "anilist_id": payload.anilist_id,
        "anilist_data": _json_safe_value(payload.anilist_data, "anilist_data"),
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
        "plugin_data": _json_safe_mapping(payload.plugin_data, "plugin_data"),
    }


def _media_search_from_dict(
    document: dict[str, Any], context: ProcessingContext
) -> None:
    # build into a scratch payload so `copy_from` can validate the result and
    # apply it without swapping the object the Jinja engine holds a reference to
    restored = MediaSearchPayload()
    restored.media_type = _enum_from_name(MediaType, document.get("media_type"))
    restored.imdb_id = document.get("imdb_id")
    restored.tmdb_id = document.get("tmdb_id")
    restored.tmdb_data = document.get("tmdb_data")
    restored.tvdb_id = document.get("tvdb_id")
    restored.tvdb_data = document.get("tvdb_data")
    restored.anilist_id = document.get("anilist_id")
    restored.anilist_data = document.get("anilist_data")
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
            genre_cls = _GENRE_ENUMS.get(str(entry.get("enum")))
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
        restored.plugin_data.update(plugin_data)

    context.media_search.copy_from(restored)


# --------------------------------------------------------------------------
# shared data
# --------------------------------------------------------------------------
def _shared_data_to_dict(
    context: ProcessingContext,
    nfo_assets: dict[TrackerSelection, str] | None = None,
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
        "dynamic_data": _json_safe_mapping(payload.dynamic_data, "dynamic_data"),
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
            tracker.name: {
                "name": host.name,
                "type": type(host).__name__,
            }
            for tracker, host in payload.uploaded_image_hosts.items()
        },
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

    dynamic_data = document.get("dynamic_data")
    if isinstance(dynamic_data, dict):
        payload.dynamic_data.update(dynamic_data)

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
            if tracker is None or not isinstance(images, dict):
                continue
            restored_images: dict[int, ImageUploadData] = {}
            for raw_index, data in images.items():
                restored_data = _image_upload_data_from_dict(data)
                if restored_data is None:
                    continue
                try:
                    restored_images[int(raw_index)] = restored_data
                except (TypeError, ValueError):
                    continue
            if restored_images:
                payload.uploaded_images[tracker] = restored_images

    uploaded_image_hosts = document.get("uploaded_image_hosts")
    if isinstance(uploaded_image_hosts, dict):
        for raw_tracker, raw_host in uploaded_image_hosts.items():
            tracker = _enum_from_name(TrackerSelection, raw_tracker)
            if tracker is None or not isinstance(raw_host, dict):
                continue
            host_cls = _IMAGE_DESTINATION_ENUMS.get(str(raw_host.get("type")))
            if host_cls is None:
                continue
            host = _enum_from_name(host_cls, raw_host.get("name"))
            if host is not None:
                payload.uploaded_image_hosts[tracker] = host  # pyright: ignore[reportArgumentType]

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
    return {
        "media_input": _media_input_to_dict(context, mediainfo_assets),
        "media_search": _media_search_to_dict(context),
        "shared_data": _shared_data_to_dict(context, nfo_assets),
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


def filter_context_document(
    document: dict[str, Any], keep_trackers: Iterable[TrackerSelection]
) -> dict[str, Any]:
    """Return a copy of `document` narrowed to `keep_trackers`.

    This is what makes saving a job partway through a run safe. Rather than
    teaching resume to skip trackers that already uploaded -- which would put a
    duplicate upload one bug away -- the deferred job is written with only the
    trackers that still need uploading. The result is structurally identical to
    a job saved before any upload was attempted, so nothing downstream needs to
    know it came from a partial run.
    """
    keep_names = {tracker.name for tracker in keep_trackers}
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
    for key in (
        "tracker_image_hosts",
        "uploaded_images",
        "uploaded_image_hosts",
        "tracker_release_data",
    ):
        value = shared_copy.get(key)
        if isinstance(value, dict):
            shared_copy[key] = {
                name: entry for name, entry in value.items() if name in keep_names
            }

    filtered["shared_data"] = shared_copy
    return filtered
