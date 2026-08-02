import asyncio
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import quote

import niquests

from src.exceptions import MediaSearchError, MediaSearchUnavailableError


class TVDBClient:
    """
    Minimal TVDB v4 client (sync) used by the media-search pipeline.

    The third-party TVDB wrapper used by the project relied on ``urllib`` without
    passing a socket timeout. These clients keep the small endpoint surface we
    need, enforce a timeout on every request, and reuse one authenticated session
    for the lifetime of a media-search backend
    """

    BASE_URL = "https://api4.thetvdb.com/v4"

    def __init__(self, api_key: str, timeout: int) -> None:
        self.api_key = api_key
        self.timeout = max(1, timeout)
        self.session = niquests.Session()
        self._token: str | None = None

    def close(self) -> None:
        self.session.close()

    def search_by_remote_id(self, remote_id: str) -> list[dict[str, Any]]:
        result = self._request(f"/search/remoteid/{quote(remote_id, safe='')}")
        return cast(list[dict[str, Any]], result) if isinstance(result, list) else []

    def get_series_extended(self, series_id: int) -> dict[str, Any]:
        result = self._request(
            f"/series/{series_id}/extended",
            params={"meta": "episodes", "short": "true"},
        )
        return cast(dict[str, Any], result) if isinstance(result, dict) else {}

    def get_series_episodes(self, series_id: int, season_type: str) -> dict[str, Any]:
        result = self._request(f"/series/{series_id}/episodes/{season_type}")
        return cast(dict[str, Any], result) if isinstance(result, dict) else {}

    def _authenticate(self) -> str:
        try:
            with self.session.post(
                f"{self.BASE_URL}/login",
                json={"apikey": self.api_key},
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()
                response_json = response.json()
        except (
            niquests.exceptions.ConnectionError,
            niquests.exceptions.Timeout,
            niquests.exceptions.ProxyError,
            niquests.exceptions.SSLError,
        ) as error:
            raise MediaSearchUnavailableError(
                "TVDB is unavailable. Check your internet connection and try again."
            ) from error
        except niquests.exceptions.RequestException as error:
            raise MediaSearchError(f"TVDB authentication failed: {error}") from error
        except (TypeError, ValueError) as error:
            raise MediaSearchError(
                "TVDB returned an invalid authentication response."
            ) from error

        if not isinstance(response_json, dict):
            raise MediaSearchError("TVDB returned an invalid authentication response.")
        data = response_json.get("data")
        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise MediaSearchError("TVDB authentication returned no token.")
        self._token = token
        return token

    def _request(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        token = self._token or self._authenticate()
        try:
            with self.session.get(
                f"{self.BASE_URL}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()
                response_json = response.json()
        except (
            niquests.exceptions.ConnectionError,
            niquests.exceptions.Timeout,
            niquests.exceptions.ProxyError,
            niquests.exceptions.SSLError,
        ) as error:
            raise MediaSearchUnavailableError(
                "TVDB is unavailable. Check your internet connection and try again."
            ) from error
        except niquests.exceptions.RequestException as error:
            raise MediaSearchError(f"TVDB request failed: {error}") from error
        except (TypeError, ValueError) as error:
            raise MediaSearchError("TVDB returned an invalid response.") from error

        if not isinstance(response_json, dict):
            raise MediaSearchError("TVDB returned an invalid response.")
        data = response_json.get("data")
        if data is None or response_json.get("status") == "failure":
            message = response_json.get("message") or "unknown error"
            raise MediaSearchError(f"TVDB request failed: {message}")
        return data


class AsyncTVDBClient:
    """Async facade over :class:`TVDBClient` for the Qt worker pipeline."""

    def __init__(self, client: TVDBClient) -> None:
        self.client = client

    @property
    def timeout(self) -> int:
        return self.client.timeout

    def close(self) -> None:
        self.client.close()

    async def search_by_remote_id(self, remote_id: str) -> list[dict[str, Any]]:
        return await self._run(self.client.search_by_remote_id, remote_id)

    async def get_series_extended(self, series_id: int) -> dict[str, Any]:
        return await self._run(self.client.get_series_extended, series_id)

    async def get_series_episodes(
        self, series_id: int, season_type: str
    ) -> dict[str, Any]:
        return await self._run(
            self.client.get_series_episodes,
            series_id,
            season_type,
        )

    async def _run(self, method: Any, *args: Any) -> Any:
        return await asyncio.wait_for(
            asyncio.to_thread(method, *args),
            timeout=self.timeout,
        )
