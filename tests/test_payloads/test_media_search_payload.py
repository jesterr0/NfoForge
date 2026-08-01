from src.enums.media_type import MediaType
from src.enums.tmdb_genres import TMDBGenreIDsMovies
from src.payloads.media_search import MediaSearchPayload
from src.plugins.metadata_provider import MetadataMediaKind, MetadataProviderResult


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


def test_merge_metadata_builds_canonical_tmdb_fallbacks() -> None:
    payload = _tmdb_payload()

    payload.merge_metadata()

    assert payload.title == "TMDb Localized"
    assert payload.original_title == "TMDb Original"
    assert payload.year == 2024
    assert payload.plot == "TMDb plot"
    assert payload.poster_url == "https://image.tmdb.org/t/p/original/poster.jpg"
    assert payload.genre_names == ("Drama", "Comedy")
    assert payload.media_kind is None
    assert payload.provider_metadata is None


def test_merge_metadata_applies_only_populated_provider_fields() -> None:
    payload = _tmdb_payload()
    original_genres = payload.genres.copy()
    provider = MetadataProviderResult(
        localized_title="Provider Localized",
        original_title="Provider Original",
        year=1999,
        plot="Provider plot",
        poster_url="https://provider.example/poster.jpg",
        genres=("Thriller",),
        media_kind=MetadataMediaKind.STAND_UP_COMEDY,
    )

    payload.merge_metadata(provider)

    assert payload.title == "Provider Localized"
    assert payload.original_title == "Provider Original"
    assert payload.year == 1999
    assert payload.plot == "Provider plot"
    assert payload.poster_url == "https://provider.example/poster.jpg"
    assert payload.genre_names == ("Thriller",)
    assert payload.media_kind is MetadataMediaKind.STAND_UP_COMEDY
    assert payload.provider_metadata is provider

    # Structural routing and database identity remain application-controlled.
    assert payload.media_type is MediaType.MOVIE
    assert payload.imdb_id == "tt1234567"
    assert payload.tmdb_id == "123"
    assert payload.genres == original_genres


def test_partial_provider_result_preserves_unset_tmdb_values() -> None:
    payload = _tmdb_payload()

    payload.merge_metadata(MetadataProviderResult(original_title="Only Override"))

    assert payload.title == "TMDb Localized"
    assert payload.original_title == "Only Override"
    assert payload.year == 2024
    assert payload.plot == "TMDb plot"
    assert payload.genre_names == ("Drama", "Comedy")


def test_reset_clears_canonical_and_raw_provider_metadata() -> None:
    payload = _tmdb_payload()
    payload.merge_metadata(
        MetadataProviderResult(
            localized_title="Provider title",
            media_kind=MetadataMediaKind.MOVIE,
        )
    )

    payload.reset()

    assert payload.provider_metadata is None
    assert payload.plot is None
    assert payload.poster_url is None
    assert payload.genre_names == ()
    assert payload.media_kind is None
