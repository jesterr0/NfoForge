import asyncio
import hashlib
from typing import Any

import niquests
import pytest

from src.backend.media_search import MediaSearchBackEnd
from src.backend.utils.tvdb_client import AsyncTVDBClient, TVDBClient
from src.enums.media_type import MediaType
from src.enums.tmdb_genres import TMDBGenreIDsMovies
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
        "src.backend.utils.tvdb_client.niquests.Session", lambda: fake_session
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
