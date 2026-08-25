import pytest

from src.backend.utils.tmdb_reference import TmdbReference, parse_tmdb_reference
from src.enums.media_type import MediaType


@pytest.mark.parametrize(
    "text",
    [
        "https://www.themoviedb.org/movie/603-the-matrix",
        "http://themoviedb.org/movie/603",
        "www.themoviedb.org/movie/603-the-matrix",
        "themoviedb.org/movie/603-the-matrix",
        "  https://www.themoviedb.org/movie/603-the-matrix  ",
        "https://www.themoviedb.org/movie/603-the-matrix?language=en-US",
        "https://www.themoviedb.org/movie/603-the-matrix/watch",
    ],
)
def test_parses_a_movie_url_in_any_shape(text: str) -> None:
    reference = parse_tmdb_reference(text)
    assert reference == TmdbReference(tmdb_id="603", media_type=MediaType.MOVIE)


@pytest.mark.parametrize(
    "text",
    [
        "https://www.themoviedb.org/tv/1396-breaking-bad",
        "themoviedb.org/tv/1396",
        "https://www.themoviedb.org/tv/1396-breaking-bad?language=en-US",
    ],
)
def test_parses_a_tv_url_in_any_shape(text: str) -> None:
    reference = parse_tmdb_reference(text)
    assert reference == TmdbReference(tmdb_id="1396", media_type=MediaType.SERIES)


@pytest.mark.parametrize(
    "text",
    [
        "tmdb:603",
        "tmdbid:603",
        "TMDB:603",
        "TMDBID:603",
        "tmdb: 603",
        "  tmdb:603  ",
    ],
)
def test_parses_an_id_prefix(text: str) -> None:
    reference = parse_tmdb_reference(text)
    assert reference == TmdbReference(tmdb_id="603", media_type=None)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "603",
        "300",
        "Cheeky 2000",
        "The Matrix",
        "tmdb:",
        "tmdb:abc",
        "not a tmdb: 603 reference",
        "tmdbidentification:603",
    ],
)
def test_leaves_a_plain_query_untouched(text: str) -> None:
    assert parse_tmdb_reference(text) is None
