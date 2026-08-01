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


def test_tmdb_uses_embedded_v4_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = MediaSearchBackEnd()
    request: dict[str, Any] = {}

    def get(*_args: object, **kwargs: object) -> _Response:
        request.update(kwargs)
        return _Response({"results": []})

    monkeypatch.setattr(backend.session, "get", get)

    assert backend.params == {"language": "en-US", "include_adult": "false"}
    assert backend.headers == {
        "Authorization": f"Bearer {MediaSearchBackEnd._get_tmdb_k()}"
    }
    assert MediaSearchBackEnd._get_tmdb_k().startswith("eyJ")
    assert backend._fetch_tmdb_results("https://example.invalid/search") == []
    assert request["headers"] == backend.headers


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
