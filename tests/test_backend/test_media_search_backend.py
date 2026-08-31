import asyncio
import hashlib
from typing import Any

import niquests
import pytest

from src.backend.media_search import MediaSearchBackEnd
from src.backend.utils.tvdb_client import AsyncTVDBClient, TVDBClient
from src.enums.media_search_mode import MediaSearchMode
from src.enums.media_type import MediaType
from src.enums.tmdb_genres import TMDBGenreIDsMovies, TMDBGenreIDsSeries
from src.exceptions import MediaSearchError, MediaSearchUnavailableError


class _Response:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload


def test_tmdb_uses_embedded_v3_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = MediaSearchBackEnd()
    request: dict[str, Any] = {}

    def get(*_args: object, **kwargs: object) -> _Response:
        request.update(kwargs)
        return _Response({"results": []})

    monkeypatch.setattr(backend.session, "get", get)

    api_key = MediaSearchBackEnd._get_tmdb_k()
    assert backend.params == {
        "api_key": api_key,
        "language": "en-US",
        "include_adult": "false",
    }
    assert hashlib.sha256(api_key.encode()).hexdigest() == (
        "2b1c33182dfef37134403968440074a72fa6f241853da4c2aafcc8b8f43c023e"
    )
    assert backend._fetch_tmdb_results("https://example.invalid/search") == []
    assert request["params"] == backend.params
    assert "headers" not in request


def test_a_user_supplied_key_replaces_the_bundled_one() -> None:
    backend = MediaSearchBackEnd(api_key="user-key")
    assert backend.params["api_key"] == "user-key"


def test_a_blank_key_falls_back_to_the_bundled_one() -> None:
    for blank in ("", "   "):
        backend = MediaSearchBackEnd(api_key=blank)
        assert backend.params["api_key"] == MediaSearchBackEnd._get_tmdb_k()


def test_update_api_key_falls_back_when_cleared() -> None:
    backend = MediaSearchBackEnd(api_key="user-key")
    backend.update_api_key("")
    assert backend.params["api_key"] == MediaSearchBackEnd._get_tmdb_k()


def test_update_api_key_swaps_in_a_new_key() -> None:
    backend = MediaSearchBackEnd()
    backend.update_api_key("new-key")
    assert backend.params["api_key"] == "new-key"


def test_tmdb_connection_failure_is_not_reported_as_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = MediaSearchBackEnd(timeout=7)

    def fail(*_args: object, **_kwargs: object) -> _Response:
        raise niquests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(backend.session, "get", fail)

    with pytest.raises(MediaSearchUnavailableError, match="TMDB search is unavailable"):
        backend._fetch_tmdb_results("https://example.invalid/search")


def test_guessit_list_title_uses_first_title(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = MediaSearchBackEnd()
    monkeypatch.setattr(
        "src.backend.media_search.guessit",
        lambda *_args, **_kwargs: {"title": ["Primary", "Alternative"], "year": "2024"},
    )

    assert backend._guessit("ignored filename") == ("Primary", "2024")


def test_best_match_prefers_exact_then_adjacent_release_year() -> None:
    results = {
        "1) Bob Dylan (1986)": {
            "title": "Bob Dylan",
            "original_title": "Bob Dylan",
            "year": "1986",
        },
        "2) Bob Dylan (1992)": {
            "title": "Bob Dylan",
            "original_title": "Bob Dylan",
            "year": "1992",
        },
        "3) Bob Dylan (1993)": {
            "title": "Bob Dylan",
            "original_title": "Bob Dylan",
            "year": "1993",
        },
    }

    assert (
        MediaSearchBackEnd.best_match_key("Bob Dylon 1993", results)
        == "3) Bob Dylan (1993)"
    )

    del results["3) Bob Dylan (1993)"]
    assert (
        MediaSearchBackEnd.best_match_key("Bob Dylon 1993", results)
        == "2) Bob Dylan (1992)"
    )


def test_best_match_does_not_promote_an_unrelated_exact_year() -> None:
    results = {
        "1) Bob Dylan (1986)": {
            "title": "Bob Dylan",
            "original_title": "Bob Dylan",
            "year": "1986",
        },
        "2) A Completely Different Film (1993)": {
            "title": "A Completely Different Film",
            "original_title": "A Completely Different Film",
            "year": "1993",
        },
    }

    assert (
        MediaSearchBackEnd.best_match_key("Bob Dylon 1993", results)
        == "1) Bob Dylan (1986)"
    )


def test_best_match_normalizes_titles_and_checks_original_title() -> None:
    results = {
        "1) Other (2001)": {
            "title": "Other",
            "original_title": "Other",
            "year": "2001",
        },
        "2) Amelie (2001)": {
            "title": "Am\u00e9lie",
            "original_title": "Le Fabuleux Destin d'Am\u00e9lie Poulain",
            "year": "2001",
        },
    }

    assert (
        MediaSearchBackEnd.best_match_key(
            "Le.Fabuleux.Destin.d.Amelie.Poulain.2001", results
        )
        == "2) Amelie (2001)"
    )


def test_best_match_without_usable_evidence_preserves_tmdb_order() -> None:
    results = {
        "first": {"title": "", "year": "not-a-year"},
        "second": {"title": None, "year": "2024"},
    }

    assert MediaSearchBackEnd.best_match_key("...", results) == "first"
    assert MediaSearchBackEnd.best_match_key("anything", {}) is None


def test_tmdb_empty_successful_search_disables_results() -> None:
    backend = MediaSearchBackEnd()
    backend.session.get = lambda *_args, **_kwargs: _Response({"results": []})  # type: ignore[method-assign]

    assert backend._parse_tmdb_api("missing title") == {}


def test_tmdb_invalid_response_is_reported() -> None:
    backend = MediaSearchBackEnd()
    backend.session.get = lambda *_args, **_kwargs: _Response([])  # type: ignore[method-assign]

    with pytest.raises(MediaSearchError, match="invalid search response"):
        backend._fetch_tmdb_results("https://example.invalid/search")


def test_tmdb_search_query_is_sent_as_a_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = MediaSearchBackEnd()
    request: dict[str, Any] = {}

    monkeypatch.setattr(
        backend,
        "_guessit",
        lambda _value: ("Fast & Furious #9", "2024"),
    )

    def get(url: str, **kwargs: object) -> _Response:
        request["url"] = url
        request.update(kwargs)
        return _Response({"results": []})

    monkeypatch.setattr(backend.session, "get", get)

    backend._parse_tmdb_api("ignored")

    assert request["url"] == "https://api.themoviedb.org/3/search/multi"
    params = request["params"]
    assert isinstance(params, dict)
    assert params["query"] == "Fast & Furious #9"
    assert params["year"] == "2024"


@pytest.mark.parametrize(
    ("search_mode", "endpoint", "year_param", "result", "expected_media_type"),
    [
        (
            MediaSearchMode.MOVIES,
            "movie",
            "primary_release_year",
            {
                "id": 1,
                "title": "Example Movie",
                "original_title": "Example Movie",
                "release_date": "2024-01-02",
            },
            "Movie",
        ),
        (
            MediaSearchMode.TV,
            "tv",
            "first_air_date_year",
            {
                "id": 2,
                "name": "Example Show",
                "original_name": "Example Show",
                "first_air_date": "2024-03-04",
            },
            "Series",
        ),
    ],
)
def test_tmdb_restricted_search_uses_dedicated_endpoint_and_media_type(
    search_mode: MediaSearchMode,
    endpoint: str,
    year_param: str,
    result: dict[str, Any],
    expected_media_type: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = MediaSearchBackEnd()
    request: dict[str, Any] = {}
    monkeypatch.setattr(backend, "_guessit", lambda _value: ("Example", "2024"))

    def get(url: str, **kwargs: object) -> _Response:
        request["url"] = url
        request.update(kwargs)
        return _Response({"results": [result]})

    monkeypatch.setattr(backend.session, "get", get)

    parsed = backend._parse_tmdb_api("ignored", search_mode)

    assert request["url"] == f"https://api.themoviedb.org/3/search/{endpoint}"
    params = request["params"]
    assert isinstance(params, dict)
    assert params[year_param] == "2024"
    assert "year" not in params
    assert next(iter(parsed.values()))["media_type"] == expected_media_type


@pytest.mark.parametrize("media_id", ["../../person/1234", "123&api_key=x", "²"])
def test_tmdb_metadata_rejects_non_decimal_ids(
    media_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = MediaSearchBackEnd()
    monkeypatch.setattr(
        backend.session,
        "get",
        lambda *_args, **_kwargs: pytest.fail("invalid IDs must not reach TMDB"),
    )

    with pytest.raises(MediaSearchError, match="decimal number"):
        backend.fetch_complete_tmdb_data_for_selection(media_id, MediaType.MOVIE)


def test_tmdb_metadata_rejects_a_mismatched_response_id() -> None:
    backend = MediaSearchBackEnd()
    backend.session.get = lambda *_args, **_kwargs: _Response(  # type: ignore[method-assign]
        {"id": 999, "title": "Wrong movie"}
    )

    with pytest.raises(MediaSearchError, match="different ID"):
        backend.fetch_complete_tmdb_data_for_selection("123", MediaType.MOVIE)


def test_tvdb_decimal_validation_does_not_convert_superscript_digits() -> None:
    backend = MediaSearchBackEnd()

    result = asyncio.run(
        backend.parse_other_ids(
            media_type=MediaType.SERIES,
            imdb_id="",
            tmdb_title="Show",
            tmdb_year=2024,
            original_language="en",
            tmdb_genres=[],
            tvdb_id="²",
        )
    )

    assert result["resolved_ids"]["result"]["tvdb_id"] is None


class _FakeTVDBSession:
    def __init__(self) -> None:
        self.post_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.post_calls.append({"url": url, **kwargs})
        return _Response({"data": {"token": "tvdb-token"}})

    def get(self, url: str, **kwargs: Any) -> _Response:
        self.get_calls.append({"url": url, **kwargs})
        if url.endswith("/search/remoteid/tt123%26x"):
            return _Response({"data": [{"series": {"id": 321}}]})
        return _Response({"data": {"id": 321, "episodes": []}})

    def close(self) -> None:
        return None


def test_tvdb_sync_and_async_clients_use_timeouts_and_reuse_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = _FakeTVDBSession()
    monkeypatch.setattr(
        "src.backend.utils.http_client.niquests.Session",
        lambda **_kwargs: fake_session,
    )
    client = TVDBClient("api-key", timeout=7)

    assert client.search_by_remote_id("tt123&x")[0]["series"]["id"] == 321
    async_client = AsyncTVDBClient(client)
    assert asyncio.run(async_client.get_series_extended(321))["id"] == 321

    assert len(fake_session.post_calls) == 1
    assert fake_session.post_calls[0]["timeout"] == 7
    assert len(fake_session.get_calls) == 2
    assert all(call["timeout"] == 7 for call in fake_session.get_calls)
    assert fake_session.get_calls[0]["url"].endswith("/search/remoteid/tt123%26x")


def test_series_tvdb_failure_is_returned_for_the_ui() -> None:
    backend = MediaSearchBackEnd()
    backend.fetch_complete_tmdb_data_for_selection = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: {
            "external_ids": {"tvdb_id": 123},
        }
    )

    async def fail_tvdb(*_args: object, **_kwargs: object) -> None:
        raise MediaSearchUnavailableError("TVDB offline")

    backend.parse_tvdb_data = fail_tvdb  # type: ignore[method-assign]

    result = asyncio.run(
        backend.parse_other_ids(
            media_type=MediaType.SERIES,
            imdb_id="tt1234567",
            tmdb_title="Show",
            tmdb_year=2024,
            original_language="en",
            tmdb_genres=[],
            tmdb_id="123",
        )
    )

    assert result["tvdb_data"] == {"success": False, "error": "TVDB offline"}


def test_manual_tvdb_id_takes_precedence_over_tmdb_external_id() -> None:
    backend = MediaSearchBackEnd()
    backend.fetch_complete_tmdb_data_for_selection = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: {"external_ids": {"tvdb_id": 222}}
    )
    received: list[tuple[str | None, int | None]] = []

    async def parse_tvdb(imdb_id: str | None, tvdb_id: int | None) -> dict[str, Any]:
        received.append((imdb_id, tvdb_id))
        return {"id": tvdb_id}

    backend.parse_tvdb_data = parse_tvdb  # type: ignore[method-assign]

    result = asyncio.run(
        backend.parse_other_ids(
            media_type=MediaType.SERIES,
            imdb_id="tt1234567",
            tmdb_title="Show",
            tmdb_year=2024,
            original_language="en",
            tmdb_genres=[],
            tmdb_id="123",
            tvdb_id="111",
        )
    )

    assert received == [("tt1234567", 111)]
    assert result["resolved_ids"]["result"]["tvdb_id"] == 111


def test_manual_tmdb_id_creates_anilist_task_from_the_fetched_record() -> None:
    # `tmdb_genres`/`original_language` describe the previously selected
    # search row, not the record a manually entered TMDB ID resolves to.
    # Both are stale here (no Animation genre, English language) to prove
    # the fetched record -- not the row -- decides the AniList lookup. This
    # is the user-visible behaviour the fix restores: an anime reached by
    # manual TMDB ID must not silently skip the AniList/MAL lookup.
    backend = MediaSearchBackEnd()
    backend.fetch_complete_tmdb_data_for_selection = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: {
            "genres": [{"id": 16, "name": "Animation"}],
            "original_language": "ja",
        }
    )
    anilist_calls: list[tuple[str, int]] = []

    async def fake_parse_ani_list(tmdb_title: str, tmdb_year: int) -> dict[str, Any]:
        anilist_calls.append((tmdb_title, tmdb_year))
        return {"id": "999"}

    backend.parse_ani_list = fake_parse_ani_list  # type: ignore[method-assign]

    result = asyncio.run(
        backend.parse_other_ids(
            media_type=MediaType.MOVIE,
            imdb_id="",
            tmdb_title="Anime Movie",
            tmdb_year=2024,
            original_language="en",
            tmdb_genres=[TMDBGenreIDsMovies.ACTION],
            tmdb_id="123",
        )
    )

    assert anilist_calls == [("Anime Movie", 2024)]
    assert result["ani_list_data"] == {"success": True, "result": {"id": "999"}}


def test_stale_anime_looking_row_does_not_trigger_anilist_when_fetched_record_disagrees() -> (
    None
):
    # Inverse of the case above: a stale row that looks like anime must not
    # win over a fetched record that says otherwise.
    backend = MediaSearchBackEnd()
    backend.fetch_complete_tmdb_data_for_selection = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: {
            "genres": [{"id": 18, "name": "Drama"}],
            "original_language": "en",
        }
    )
    anilist_calls: list[tuple[str, int]] = []

    async def fake_parse_ani_list(tmdb_title: str, tmdb_year: int) -> dict[str, Any]:
        anilist_calls.append((tmdb_title, tmdb_year))
        return {"id": "999"}

    backend.parse_ani_list = fake_parse_ani_list  # type: ignore[method-assign]

    result = asyncio.run(
        backend.parse_other_ids(
            media_type=MediaType.MOVIE,
            imdb_id="",
            tmdb_title="Drama Movie",
            tmdb_year=2024,
            original_language="ja",
            tmdb_genres=[TMDBGenreIDsMovies.ANIMATION],
            tmdb_id="123",
        )
    )

    assert anilist_calls == []
    assert "ani_list_data" not in result


def test_series_animation_genre_triggers_anilist_without_a_manual_id() -> None:
    # A series row's genres are TMDBGenreIDsSeries members, not
    # TMDBGenreIDsMovies. `tmdb_id=""` keeps `tmdb_complete_data` at None, so
    # Task 16's fetched-record override cannot mask whether the row's own
    # genres are enough to trigger the AniList lookup on the ordinary
    # browse-and-select path (no manually entered TMDB ID).
    backend = MediaSearchBackEnd()
    anilist_calls: list[tuple[str, int]] = []

    async def fake_parse_ani_list(tmdb_title: str, tmdb_year: int) -> dict[str, Any]:
        anilist_calls.append((tmdb_title, tmdb_year))
        return {"id": 1, "idMal": 2}

    backend.parse_ani_list = fake_parse_ani_list  # type: ignore[method-assign]

    result = asyncio.run(
        backend.parse_other_ids(
            media_type=MediaType.SERIES,
            imdb_id="",
            tmdb_title="Some Anime",
            tmdb_year=2020,
            original_language="ja",
            tmdb_genres=[TMDBGenreIDsSeries.ANIMATION],
            tmdb_id="",
        )
    )

    assert anilist_calls == [("Some Anime", 2020)]
    assert result["ani_list_data"] == {
        "success": True,
        "result": {"id": 1, "idMal": 2},
    }


def test_tmdb_search_failure_scrubs_the_api_key_from_the_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A niquests error stringifies the request URL, which carries `api_key=`.

    That message reaches the log and an on-screen error dialog, so the key
    must not survive into it.
    """
    backend = MediaSearchBackEnd()

    def get(*_args: object, **_kwargs: object) -> _Response:
        raise niquests.exceptions.RequestException(
            "503 Server Error for url: "
            "https://api.themoviedb.org/3/search/multi"
            "?api_key=topsecretkeyvalue&page=1"
        )

    monkeypatch.setattr(backend.session, "get", get)

    with pytest.raises(MediaSearchError) as error:
        backend._fetch_tmdb_results("https://api.themoviedb.org/3/search/multi")

    assert "topsecretkeyvalue" not in str(error.value)
    assert "[redacted]" in str(error.value)


def test_tmdb_metadata_failure_scrubs_the_api_key_from_the_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same leak on the metadata endpoint used after a selection is made."""
    backend = MediaSearchBackEnd()

    def get(*_args: object, **_kwargs: object) -> _Response:
        raise niquests.exceptions.RequestException(
            "503 Server Error for url: "
            "https://api.themoviedb.org/3/movie/550988"
            "?api_key=topsecretkeyvalue&language=en"
        )

    monkeypatch.setattr(backend.session, "get", get)

    with pytest.raises(MediaSearchError) as error:
        backend.fetch_complete_tmdb_data_for_selection("550988", MediaType.MOVIE)

    assert "topsecretkeyvalue" not in str(error.value)
    assert "[redacted]" in str(error.value)


def _movie_record(tmdb_id: int = 603) -> dict[str, Any]:
    return {
        "id": tmdb_id,
        "title": "The Matrix",
        "original_title": "The Matrix",
        "release_date": "1999-03-30",
        "overview": "A hacker learns the truth.",
        "vote_average": 8.234,
        "poster_path": "/poster.jpg",
        "genres": [{"id": 28, "name": "Action"}],
        "original_language": "en",
    }


def _series_record(tmdb_id: int = 1396) -> dict[str, Any]:
    return {
        "id": tmdb_id,
        "name": "Breaking Bad",
        "original_name": "Breaking Bad",
        "first_air_date": "2008-01-20",
        "overview": "A teacher turns to crime.",
        "vote_average": 8.9,
        "poster_path": "/poster2.jpg",
        "genres": [{"id": 18, "name": "Drama"}],
        "original_language": "en",
    }


def test_resolve_tmdb_reference_uses_the_hinted_media_type() -> None:
    """A URL-derived reference already knows its media type, so only that
    one endpoint should ever be hit."""
    backend = MediaSearchBackEnd()
    calls: list[MediaType] = []

    def fake_fetch(_tmdb_id: str, media_type: MediaType) -> dict[str, Any]:
        calls.append(media_type)
        return _movie_record()

    backend.fetch_complete_tmdb_data_for_selection = (  # type: ignore[method-assign]
        fake_fetch
    )

    result = backend.resolve_tmdb_reference(
        "603", MediaType.MOVIE, MediaSearchMode.BOTH
    )

    assert calls == [MediaType.MOVIE]
    row = next(iter(result.values()))
    assert row["tmdb_id"] == "603"
    assert row["title"] == "The Matrix"
    assert row["year"] == "1999"
    assert row["full_release_date"] == "03-30-1999"
    assert row["media_type"] == "Movie"
    assert row["genre_ids"] == [TMDBGenreIDsMovies.ACTION]
    assert backend.media_data == result


def test_resolve_tmdb_reference_falls_back_to_tv_when_movie_lookup_fails() -> None:
    """A bare `tmdb:` id carries no media-type marker, so `BOTH` mode tries
    movie first and falls back to tv on a `MediaSearchError`."""
    backend = MediaSearchBackEnd()
    calls: list[MediaType] = []

    def fake_fetch(_tmdb_id: str, media_type: MediaType) -> dict[str, Any]:
        calls.append(media_type)
        if media_type is MediaType.MOVIE:
            raise MediaSearchError("TMDB returned a different ID than requested.")
        return _series_record()

    backend.fetch_complete_tmdb_data_for_selection = (  # type: ignore[method-assign]
        fake_fetch
    )

    result = backend.resolve_tmdb_reference("1396", None, MediaSearchMode.BOTH)

    assert calls == [MediaType.MOVIE, MediaType.SERIES]
    row = next(iter(result.values()))
    assert row["media_type"] == "Series"
    assert row["title"] == "Breaking Bad"


@pytest.mark.parametrize(
    "search_mode,expected_calls",
    [
        (MediaSearchMode.MOVIES, [MediaType.MOVIE]),
        (MediaSearchMode.TV, [MediaType.SERIES]),
    ],
)
def test_resolve_tmdb_reference_respects_a_restricted_search_mode(
    search_mode: MediaSearchMode, expected_calls: list[MediaType]
) -> None:
    """A restricted search mode never tries the other media type, even on
    failure."""
    backend = MediaSearchBackEnd()
    calls: list[MediaType] = []

    def fake_fetch(_tmdb_id: str, media_type: MediaType) -> dict[str, Any]:
        calls.append(media_type)
        raise MediaSearchError("not found")

    backend.fetch_complete_tmdb_data_for_selection = (  # type: ignore[method-assign]
        fake_fetch
    )

    with pytest.raises(MediaSearchError):
        backend.resolve_tmdb_reference("999999", None, search_mode)

    assert calls == expected_calls


def test_resolve_tmdb_reference_raises_when_no_candidate_matches() -> None:
    backend = MediaSearchBackEnd()

    def fake_fetch(_tmdb_id: str, media_type: MediaType) -> dict[str, Any]:
        raise MediaSearchError(f"not found as {media_type.value}")

    backend.fetch_complete_tmdb_data_for_selection = (  # type: ignore[method-assign]
        fake_fetch
    )

    with pytest.raises(MediaSearchError, match="Series"):
        backend.resolve_tmdb_reference("999999", None, MediaSearchMode.BOTH)


def test_resolve_tmdb_reference_stops_immediately_on_network_outage() -> None:
    """No point trying the other media type against a dead connection."""
    backend = MediaSearchBackEnd()
    calls: list[MediaType] = []

    def fake_fetch(_tmdb_id: str, media_type: MediaType) -> dict[str, Any]:
        calls.append(media_type)
        raise MediaSearchUnavailableError("TMDB search is unavailable.")

    backend.fetch_complete_tmdb_data_for_selection = (  # type: ignore[method-assign]
        fake_fetch
    )

    with pytest.raises(MediaSearchUnavailableError):
        backend.resolve_tmdb_reference("603", None, MediaSearchMode.BOTH)

    assert calls == [MediaType.MOVIE]


def test_resolve_tmdb_reference_rejects_a_record_with_no_release_date() -> None:
    backend = MediaSearchBackEnd()
    backend.fetch_complete_tmdb_data_for_selection = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: {**_movie_record(), "release_date": ""}
    )

    with pytest.raises(MediaSearchError, match="release date"):
        backend.resolve_tmdb_reference("603", MediaType.MOVIE, MediaSearchMode.BOTH)
