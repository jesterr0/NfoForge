import asyncio
from typing import Any

import niquests
import pytest

from src.backend.media_search import MediaSearchBackEnd
from src.enums.media_type import MediaType
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


def test_tmdb_connection_failure_is_not_reported_as_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = MediaSearchBackEnd(api_key="key", timeout=7)

    def fail(*_args: object, **_kwargs: object) -> _Response:
        raise niquests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(backend.session, "get", fail)

    with pytest.raises(MediaSearchUnavailableError, match="TMDB search is unavailable"):
        backend._fetch_tmdb_results("https://example.invalid/search")


def test_guessit_list_title_uses_first_title(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = MediaSearchBackEnd(api_key="key")
    monkeypatch.setattr(
        "src.backend.media_search.guessit",
        lambda *_args, **_kwargs: {"title": ["Primary", "Alternative"], "year": "2024"},
    )

    assert backend._guessit("ignored filename") == ("Primary", "2024")


def test_tmdb_empty_successful_search_disables_results() -> None:
    backend = MediaSearchBackEnd(api_key="key")
    backend.session.get = lambda *_args, **_kwargs: _Response({"results": []})  # type: ignore[method-assign]

    assert backend._parse_tmdb_api("missing title") == {}


def test_tmdb_invalid_response_is_reported() -> None:
    backend = MediaSearchBackEnd(api_key="key")
    backend.session.get = lambda *_args, **_kwargs: _Response([])  # type: ignore[method-assign]

    with pytest.raises(MediaSearchError, match="invalid search response"):
        backend._fetch_tmdb_results("https://example.invalid/search")


def test_required_series_tvdb_failure_propagates() -> None:
    backend = MediaSearchBackEnd(api_key="key")
    backend.fetch_complete_tmdb_data_for_selection = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: {
            "external_ids": {"tvdb_id": 123},
        }
    )

    async def fail_tvdb(*_args: object, **_kwargs: object) -> None:
        raise MediaSearchUnavailableError("TVDB offline")

    backend.parse_tvdb_data = fail_tvdb  # type: ignore[method-assign]

    with pytest.raises(MediaSearchUnavailableError, match="TVDB offline"):
        asyncio.run(
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


def test_optional_imdb_failure_remains_non_fatal() -> None:
    backend = MediaSearchBackEnd(api_key="key")
    backend.fetch_complete_tmdb_data_for_selection = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: {}
    )

    async def fail_imdb(*_args: object, **_kwargs: object) -> None:
        raise MediaSearchUnavailableError("IMDb offline")

    backend.parse_imdb_data = fail_imdb  # type: ignore[method-assign]

    result = asyncio.run(
        backend.parse_other_ids(
            media_type=MediaType.MOVIE,
            imdb_id="tt1234567",
            tmdb_title="Movie",
            tmdb_year=2024,
            original_language="en",
            tmdb_genres=[],
            tmdb_id="123",
        )
    )

    assert result["imdb_data"] == {"success": False, "error": "IMDb offline"}
