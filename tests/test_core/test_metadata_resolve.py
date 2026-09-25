"""Identifying a release and merging its metadata without the Media Search page."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from nfoforge.context.processing_context import ProcessingContext
from nfoforge.core.metadata.resolve import (
    ReleaseIds,
    apply_search_result,
    choose_result,
    genre_enums_from_tmdb,
    lookup_metadata,
    metadata_errors,
)
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.tmdb_genres import TMDBGenreIDsMovies, TMDBGenreIDsSeries

MOVIE_ROW: dict[str, Any] = {
    "media_type": "movie",
    "title": "The Movie",
    "year": "2024",
    "original_title": "The Movie",
    "raw_data": {"original_language": "en"},
    "genre_ids": [TMDBGenreIDsMovies.ACTION],
}


class _FakeBackend:
    timeout = 5

    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.results = results or {}

    async def parse_other_ids(self, *args: Any) -> dict[str, Any]:
        self.calls.append(args)
        return dict(self.results)


def _lookup(backend: _FakeBackend, row: dict[str, Any], **kwargs: Any) -> Any:
    config = kwargs.pop("config", SimpleNamespace())
    return asyncio.run(
        lookup_metadata(
            cast(Any, backend),
            row,
            ReleaseIds(imdb_id="tt1"),
            config=cast(Any, config),
            context=ProcessingContext(),
            transformer_id=kwargs.pop("transformer_id", None),
        )
    )


# --------------------------------------------------------------------------
# lookup
# --------------------------------------------------------------------------
def test_series_genres_reach_the_lookup() -> None:
    """Filtering for movie genres dropped every series genre, so anime series
    never reached the AniList lookup."""
    backend = _FakeBackend()
    row = {**MOVIE_ROW, "media_type": "tv", "genre_ids": [TMDBGenreIDsSeries.ANIMATION]}

    _lookup(backend, row)

    media_type, imdb_id, title, year, language, genres, *_ = backend.calls[0]
    assert media_type is MediaType.SERIES
    assert (imdb_id, title, year, language) == ("tt1", "The Movie", 2024, "en")
    assert genres == [TMDBGenreIDsSeries.ANIMATION]


def test_a_failing_transformer_is_recorded_not_raised() -> None:
    def fail(*_args: Any) -> Any:
        raise RuntimeError("plugin broke")

    config = SimpleNamespace(plugin_manager=SimpleNamespace(transform_metadata=fail))

    results = _lookup(_FakeBackend(), MOVIE_ROW, config=config, transformer_id="p")

    assert results["metadata_transformation"] == {
        "success": False,
        "error": "plugin broke",
    }
    assert metadata_errors(results).transformer == "plugin broke"


def test_metadata_errors() -> None:
    assert metadata_errors(None).tvdb is None
    errors = metadata_errors(
        {
            "tvdb_data": {"success": False, "error": "tvdb down"},
            "metadata_transformation": {"success": True, "result": object()},
        }
    )
    assert errors.tvdb == "tvdb down"
    assert errors.transformer is None


# --------------------------------------------------------------------------
# merging
# --------------------------------------------------------------------------
def test_the_chosen_row_is_recorded() -> None:
    context = ProcessingContext()

    transformed = apply_search_result(
        context, MOVIE_ROW, ReleaseIds(imdb_id="tt1", tmdb_id="42")
    )

    search = context.media_search
    assert transformed is False
    assert context.media_input.media_type is MediaType.MOVIE
    assert search.media_type is MediaType.MOVIE
    assert (search.imdb_id, search.tmdb_id, search.tvdb_id) == ("tt1", "42", None)
    assert search.year == 2024
    assert search.genres == [TMDBGenreIDsMovies.ACTION]


def test_resolved_and_tvdb_ids_win_over_typed_ones() -> None:
    context = ProcessingContext()

    apply_search_result(
        context,
        MOVIE_ROW,
        ReleaseIds(imdb_id="tt-typed", tvdb_id="typed"),
        media_data={
            "resolved_ids": {"success": True, "result": {"imdb_id": "tt-found"}},
            "tvdb_data": {"success": True, "result": {"id": 77}},
        },
    )

    assert context.media_search.imdb_id == "tt-found"
    assert context.media_search.tvdb_id == "77"


def test_without_anyone_to_ask_a_missing_mal_id_is_skipped() -> None:
    context = ProcessingContext()

    apply_search_result(
        context,
        MOVIE_ROW,
        ReleaseIds(),
        media_data={"ani_list_data": {"success": True, "result": None}},
    )

    assert context.media_search.mal_id is None


def test_an_answered_mal_id_is_used() -> None:
    context = ProcessingContext()

    apply_search_result(
        context,
        MOVIE_ROW,
        ReleaseIds(),
        media_data={"ani_list_data": {"success": True, "result": None}},
        ask_mal_id=lambda: 4242,
    )

    assert context.media_search.mal_id == "4242"


def test_an_unknown_media_type_is_refused() -> None:
    with pytest.raises(ValueError):
        apply_search_result(
            ProcessingContext(), {**MOVIE_ROW, "media_type": ""}, ReleaseIds()
        )


def test_a_record_with_empty_genres_is_not_backfilled_from_the_row() -> None:
    assert genre_enums_from_tmdb(MediaType.MOVIE, {"genres": []}, MOVIE_ROW) == []
    assert genre_enums_from_tmdb(MediaType.MOVIE, {}, MOVIE_ROW) == [
        TMDBGenreIDsMovies.ACTION
    ]


# --------------------------------------------------------------------------
# choosing without a person
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("keys", "preferred", "expected"),
    [
        (["a", "b"], "b", "b"),
        (["a"], None, "a"),
        (["a", "b"], None, None),
        ([], None, None),
        (["a", "b"], "gone", None),
    ],
)
def test_choose_result(
    keys: list[str], preferred: str | None, expected: str | None
) -> None:
    assert choose_result(keys, preferred) == expected
