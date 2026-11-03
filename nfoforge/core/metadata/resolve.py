"""Searching for a release, looking up its IDs, and merging it all into the run.

The desktop Media Search page shows the search results, lets the user pick
one and edit its IDs, then runs these on worker threads. A headless run calls
them directly. Asking the user anything -- which result, a missing MAL ID,
whether to go on without TVDB -- stays with the caller.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from nfoforge.backend.media_search import MediaSearchBackEnd
from nfoforge.backend.utils.title_inference import MediaTitleInferer
from nfoforge.backend.utils.tmdb_reference import TmdbReference
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.enums.media_search_mode import MediaSearchMode
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.tmdb_genres import TMDBGenreIDsMovies, TMDBGenreIDsSeries
from nfoforge.exceptions import MediaSearchError, MediaSearchUnavailableError
from nfoforge.logger.nfo_forge_logger import LOG
from nfoforge.payloads.media_search import MediaSearchPayload
from nfoforge.plugins.api import (
    MetadataInputContext,
    MetadataTransformContext,
    MetadataTransformRequest,
)
from nfoforge.utils.super_sub import normalize_super_sub

if TYPE_CHECKING:
    from nfoforge.config.config import ConfigManager
    from nfoforge.config.models import AppConfig
    from nfoforge.plugins.manager import PluginManager

type Genre = TMDBGenreIDsMovies | TMDBGenreIDsSeries


class SearchBackend(Protocol):
    def _parse_tmdb_api(
        self, media_str: str, search_mode: MediaSearchMode
    ) -> dict[str, dict[str, Any]]: ...

    def resolve_tmdb_reference(
        self,
        tmdb_id: str,
        media_type: MediaType | None,
        search_mode: MediaSearchMode,
    ) -> dict[str, dict[str, Any]]: ...


# --------------------------------------------------------------------------
# searching
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MediaSearchJobResult:
    """Combined title-inference and TMDB search result."""

    query: str | None
    results: OrderedDict[str, Any]
    title_error: str | None = None
    preferred_result_key: str | None = None


def run_media_search(
    backend: SearchBackend,
    query: str | None,
    input_path: Path | None,
    selected_files: tuple[Path, ...],
    search_mode: MediaSearchMode = MediaSearchMode.BOTH,
) -> MediaSearchJobResult:
    """Search TMDB for `query`, inferring it from the input when None.

    `preferred_result_key` is the closest title and year match, which is what
    a headless run takes.
    """
    if query is None:
        if input_path is None:
            return MediaSearchJobResult(
                query=None,
                results=OrderedDict(),
                title_error="Failed to load the selected media path.",
            )

        try:
            inference = MediaTitleInferer().infer(
                input_path,
                video_files=selected_files,
            )
        except Exception as error:
            return MediaSearchJobResult(
                query=None,
                results=OrderedDict(),
                title_error=str(error) or "Unable to determine a media title.",
            )

        query = inference.title
        LOG.info(
            LOG.LOG_SOURCE.BE,
            f"Inferred media search title {query!r} "
            f"(confidence: {inference.confidence:.1%})",
        )

    results = OrderedDict(backend._parse_tmdb_api(query, search_mode))
    return MediaSearchJobResult(
        query=query,
        results=results,
        preferred_result_key=MediaSearchBackEnd.best_match_key(query, results),
    )


def run_tmdb_id_lookup(
    backend: SearchBackend,
    reference: TmdbReference,
    search_mode: MediaSearchMode = MediaSearchMode.BOTH,
) -> MediaSearchJobResult:
    """Resolve a TMDB URL/ID given in place of a search.

    A `MediaSearchError` (bad ID, no such record, missing release date, ...)
    is reported the same way a zero-hit text search is -- an empty result set.
    A `MediaSearchUnavailableError` (network outage) propagates, as it does
    for a text search.
    """
    try:
        results = backend.resolve_tmdb_reference(
            reference.tmdb_id, reference.media_type, search_mode
        )
    except MediaSearchUnavailableError:
        raise
    except MediaSearchError:
        results = {}

    return MediaSearchJobResult(query=None, results=OrderedDict(results))


# --------------------------------------------------------------------------
# looking up IDs and the transformer
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ReleaseIds:
    """The IDs a release is looked up by, as typed or detected."""

    imdb_id: str = ""
    tmdb_id: str = ""
    tvdb_id: str = ""


def metadata_transformer_id(
    settings: AppConfig, plugin_manager: PluginManager
) -> str | None:
    """The configured metadata transformer plugin, if it can run."""
    if not settings.general.enable_plugins:
        return None
    plugin_id = settings.plugins.metadata_transformer
    if not plugin_id:
        return None
    record = plugin_manager.get(plugin_id)
    if record is None or record.definition.metadata_transformer is None:
        return None
    return plugin_id


def _result_genres(item_data: dict[str, Any]) -> list[Genre]:
    genre_ids = item_data.get("genre_ids")
    if not isinstance(genre_ids, list):
        return []
    return [
        genre
        for genre in genre_ids
        if isinstance(genre, TMDBGenreIDsMovies | TMDBGenreIDsSeries)
    ]


async def lookup_metadata(
    backend: MediaSearchBackEnd,
    item_data: dict[str, Any],
    ids: ReleaseIds,
    *,
    config: ConfigManager,
    context: ProcessingContext,
    transformer_id: str | None,
) -> dict[str, Any]:
    """Look up the chosen result's other IDs and metadata, then transform it.

    `context.media_search` must already hold the chosen result (see
    `apply_search_result`): the transformer runs on a copy of it with the
    lookup applied, so a failing transformer changes nothing. Its outcome is
    recorded under `metadata_transformation` either way.
    """
    raw_data = item_data.get("raw_data")
    year = item_data.get("year")
    results = await backend.parse_other_ids(
        MediaType.search_type(str(item_data.get("media_type"))) or MediaType.MOVIE,
        ids.imdb_id,
        str(item_data.get("title") or ""),
        int(year) if isinstance(year, int | str) else 0,
        str(raw_data.get("original_language") or "")
        if isinstance(raw_data, dict)
        else "",
        _result_genres(item_data),
        ids.tmdb_id,
        ids.tvdb_id,
    )
    if not transformer_id:
        return results

    payload = deepcopy(context.media_search)
    payload.apply_lookup_results(results)
    payload.populate_from_tmdb()
    try:
        transformed = config.plugin_manager.transform_metadata(
            transformer_id,
            MetadataTransformRequest(
                config=config,
                context=MetadataTransformContext(
                    media_input=MetadataInputContext(
                        input_path=context.media_input.input_path,
                        media_type=context.media_input.media_type,
                        working_dir=context.media_input.working_dir,
                        files=tuple(context.media_input.file_list),
                    ),
                    media_search=payload,
                ),
                payload=payload,
                timeout=backend.timeout,
            ),
        )
        results["metadata_transformation"] = {"success": True, "result": transformed}
    except Exception as error:
        results["metadata_transformation"] = {"success": False, "error": str(error)}
    return results


def _result_error(result: object) -> str | None:
    if not isinstance(result, dict) or result.get("success") is not False:
        return None
    error = result.get("error")
    return str(error) if error else "Unknown metadata error"


@dataclass(frozen=True, slots=True)
class MetadataErrors:
    """What part of a lookup failed. The run survives both."""

    transformer: str | None = None
    """The transformer failed; TMDb data is used instead."""
    tvdb: str | None = None
    """TVDB failed; a series then has to be mapped by hand."""


def metadata_errors(media_data: dict[str, Any] | None) -> MetadataErrors:
    if not media_data:
        return MetadataErrors()
    return MetadataErrors(
        transformer=_result_error(media_data.get("metadata_transformation")),
        tvdb=_result_error(media_data.get("tvdb_data")),
    )


# --------------------------------------------------------------------------
# merging into the run
# --------------------------------------------------------------------------
def genre_enums_from_tmdb(
    media_type: MediaType | None,
    tmdb_data: dict[str, Any] | None,
    item_data: dict[str, Any] | None,
) -> list[Genre]:
    """Genre enums from the fetched record, falling back to the search row.

    A complete TMDB record carries `genres` as objects with an `id`; a
    search result carries `genre_ids` as already-resolved genre enums.
    Prefer the former since it reflects a manually entered TMDB ID, and
    only fall back to the row when the record has no usable `genres` key
    at all. TMDB legitimately returns `genres: []` for some titles, and
    that empty-but-present list must be accepted as-is rather than
    treated as "missing" and backfilled from an unrelated search row.
    """
    enum_class: type[TMDBGenreIDsMovies] | type[TMDBGenreIDsSeries] = (
        TMDBGenreIDsSeries if media_type is MediaType.SERIES else TMDBGenreIDsMovies
    )

    if tmdb_data:
        raw_genres = tmdb_data.get("genres")
        if isinstance(raw_genres, list):
            resolved: list[Genre] = []
            for entry in raw_genres:
                if not isinstance(entry, dict) or "id" not in entry:
                    continue
                try:
                    resolved.append(enum_class(entry["id"]))
                except ValueError:
                    resolved.append(enum_class.UNDEFINED)
            return resolved

    if item_data:
        genre_ids = item_data.get("genre_ids")
        if isinstance(genre_ids, list):
            return [genre for genre in genre_ids if isinstance(genre, enum_class)]

    return []


def apply_anilist_data(
    media_search: MediaSearchPayload, anilist_data: dict[str, Any]
) -> None:
    media_search.anilist_data = anilist_data
    anilist_id = anilist_data.get("id")
    mal_id = anilist_data.get("idMal")
    media_search.anilist_id = str(anilist_id) if anilist_id is not None else None
    media_search.mal_id = str(mal_id) if mal_id is not None else None


def apply_search_result(
    context: ProcessingContext,
    item_data: dict[str, Any],
    ids: ReleaseIds,
    *,
    alternative_title: str | None = None,
    media_data: dict[str, Any] | None = None,
    ask_mal_id: Callable[[], int | None] | None = None,
) -> bool:
    """Merge the chosen search result, and any lookup for it, into the run.

    Without `media_data` this records the chosen result alone, which is what
    `lookup_metadata` needs before it runs. With it, the complete TMDB record,
    resolved IDs, TVDB and AniList data are merged in, then the transformer's
    payload if it succeeded.

    `alternative_title` is one of TMDB's alternative titles picked for this
    upload; it outranks both TMDB's own title and the transformer's.
    `ask_mal_id` is asked when AniList knows the release but has no MAL ID;
    without it the MAL lookup is skipped.

    Returns whether the transformer's payload was applied.
    """
    media_search = context.media_search
    prompted_anilist_data: dict[str, Any] | None = None

    # update both payloads with the correct MediaType
    context.media_input.media_type = media_search.media_type = (
        MediaType.strict_search_type(str(item_data.get("media_type") or ""))
    )
    media_search.imdb_id = ids.imdb_id or None
    media_search.tmdb_id = ids.tmdb_id or None
    media_search.tvdb_id = ids.tvdb_id or None
    media_search.tmdb_data = item_data.get("raw_data")
    media_search.tvdb_data = None

    # TMDB's own title for the record, unless the user picked one of TMDB's
    # alternatives. `populate_from_tmdb` below resolves the two.
    media_search.title = item_data.get("title")
    media_search.title_override = alternative_title
    year_value = item_data.get("year")
    media_search.year = (
        int(year_value)
        if isinstance(year_value, int | str)
        and not isinstance(year_value, bool)
        and str(year_value).isdecimal()
        else None
    )
    original_title = item_data.get("original_title")
    media_search.original_title = (
        normalize_super_sub(original_title) if original_title else None
    )

    if media_data:
        tmdb_complete_data = media_data.get("tmdb_complete_data")
        if tmdb_complete_data and tmdb_complete_data.get("success") is True:
            # the complete record is the primary tmdb_data
            media_search.tmdb_data = tmdb_complete_data.get("result")

        resolved_ids = media_data.get("resolved_ids")
        if resolved_ids and resolved_ids.get("success") is True:
            resolved_result = resolved_ids.get("result")
            if isinstance(resolved_result, dict):
                if resolved_result.get("imdb_id"):
                    media_search.imdb_id = str(resolved_result["imdb_id"])
                if resolved_result.get("tvdb_id"):
                    media_search.tvdb_id = str(resolved_result["tvdb_id"])

        tvdb_data = media_data.get("tvdb_data")
        if tvdb_data and tvdb_data.get("success") is True:
            tvdb_data_result = tvdb_data.get("result")
            if isinstance(tvdb_data_result, dict):
                media_search.tvdb_data = tvdb_data_result
                if tvdb_data_result.get("id"):
                    media_search.tvdb_id = str(tvdb_data_result["id"])

        ani_list_data = media_data.get("ani_list_data")
        if ani_list_data and ani_list_data.get("success") is True:
            ani_list_data_result = ani_list_data.get("result")
            if not ani_list_data_result and ask_mal_id is not None:
                mal_value = ask_mal_id()
                if mal_value is not None:
                    ani_list_data_result = {
                        "id": str(mal_value),
                        "idMal": str(mal_value),
                    }
                    prompted_anilist_data = ani_list_data_result
            if isinstance(ani_list_data_result, dict):
                apply_anilist_data(media_search, ani_list_data_result)
    else:
        LOG.info(
            LOG.LOG_SOURCE.BE,
            f"Using TMDB title '{media_search.title}'"
            + (" (alternative title chosen by the user)" if alternative_title else ""),
        )

    # `genres` must agree with `genre_names`, which `populate_from_tmdb`
    # rewrites from `tmdb_data`, so it is computed after any complete record
    # has replaced `tmdb_data` above.
    media_search.genres = genre_enums_from_tmdb(
        media_search.media_type, media_search.tmdb_data, item_data
    )
    media_search.populate_from_tmdb()

    transformed_result = (media_data or {}).get("metadata_transformation")
    if not (
        isinstance(transformed_result, dict)
        and transformed_result.get("success") is True
        and isinstance(transformed_result.get("result"), MediaSearchPayload)
    ):
        return False

    media_search.copy_from(transformed_result["result"])
    # The transformer ran on a snapshot taken before anyone could be asked
    # for a missing MAL ID, so an answer given since outranks that copy.
    if prompted_anilist_data is not None:
        apply_anilist_data(media_search, prompted_anilist_data)
    # A title picked for this upload outranks one the transformer derived.
    if alternative_title:
        media_search.title_override = alternative_title
        media_search.title = normalize_super_sub(alternative_title)
    if media_search.media_type is not None:
        context.media_input.media_type = media_search.media_type
    return True


def choose_result(results: Sequence[str], preferred_key: str | None) -> str | None:
    """The search result a headless run takes: the closest title and year.

    None when there is no result, or no single best one to take.
    """
    if preferred_key is not None and preferred_key in results:
        return preferred_key
    return results[0] if len(results) == 1 else None
