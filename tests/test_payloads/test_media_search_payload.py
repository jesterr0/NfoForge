import pytest

from src.enums.media_type import MediaType
from src.enums.tmdb_genres import TMDBGenreIDsMovies
from src.payloads.media_search import MediaSearchPayload
from src.plugins.api import MetadataMediaKind


def _tmdb_payload() -> MediaSearchPayload:
    return MediaSearchPayload(
        media_type=MediaType.MOVIE,
        imdb_id="tt1234567",
        tmdb_id="123",
        tmdb_data={
            "title": "TMDb Localized",
            "original_title": "TMDb Original",
            "release_date": "2024-03-02",
            "overview": "TMDb plot",
            "poster_path": "/poster.jpg",
            "genres": [
                {"id": 18, "name": "Drama"},
                {"id": 35, "name": "Comedy"},
            ],
        },
        genres=[TMDBGenreIDsMovies.DRAMA],
    )


def test_populate_from_tmdb_builds_canonical_fallbacks() -> None:
    payload = _tmdb_payload()

    payload.populate_from_tmdb()

    assert payload.title == "TMDb Localized"
    assert payload.original_title == "TMDb Original"
    assert payload.year == 2024
    assert payload.plot == "TMDb plot"
    assert payload.poster_url == "https://image.tmdb.org/t/p/original/poster.jpg"
    assert payload.genre_names == ("Drama", "Comedy")
    assert payload.media_kind is None


def test_copy_from_commits_a_complete_transformed_payload() -> None:
    payload = _tmdb_payload()
    payload.populate_from_tmdb()
    transformed = _tmdb_payload()
    transformed.populate_from_tmdb()
    transformed.title = "Provider Localized"
    transformed.original_title = "Provider Original"
    transformed.year = 1999
    transformed.genre_names = ("Thriller",)
    transformed.media_kind = MetadataMediaKind.STAND_UP_COMEDY
    transformed.plugin_data["example"] = {"matched": True}

    payload.copy_from(transformed)

    assert payload.title == "Provider Localized"
    assert payload.original_title == "Provider Original"
    assert payload.year == 1999
    assert payload.genre_names == ("Thriller",)
    assert payload.media_kind is MetadataMediaKind.STAND_UP_COMEDY
    assert payload.plugin_data == {"example": {"matched": True}}


def test_validate_rejects_an_invalid_plugin_field() -> None:
    payload = _tmdb_payload()
    payload.year = True  # type: ignore[assignment]

    with pytest.raises(TypeError, match="year"):
        payload.validate()


def test_reset_clears_canonical_and_plugin_metadata() -> None:
    payload = _tmdb_payload()
    payload.populate_from_tmdb()
    payload.media_kind = MetadataMediaKind.MOVIE
    payload.plugin_data["example"] = "value"

    payload.reset()

    assert payload.plot is None
    assert payload.poster_url is None
    assert payload.genre_names == ()
    assert payload.media_kind is None
    assert payload.plugin_data == {}
