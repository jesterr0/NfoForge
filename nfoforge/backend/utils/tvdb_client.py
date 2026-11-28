import asyncio
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import quote

import niquests

from nfoforge.backend.utils.http_client import new_http_session
from nfoforge.exceptions import MediaSearchError, MediaSearchUnavailableError

# TVDB keys languages by ISO 639-2/T, plus a few regional codes of its own
# (`pt` is Brazilian Portuguese, `por` is Portugal's).
_TVDB_REGIONAL_LANGUAGES = {"pt-BR": "pt", "zh-TW": "zhtw", "zh-HK": "yue"}
_TVDB_LANGUAGES = {
    "af": "afr", "ar": "ara", "az": "aze", "bg": "bul", "bn": "ben",
    "ca": "cat", "cs": "ces", "cy": "cym", "da": "dan", "de": "deu",
    "el": "ell", "en": "eng", "es": "spa", "et": "est", "eu": "eus",
    "fa": "fas", "fi": "fin", "fr": "fra", "ga": "gle", "gl": "glg",
    "he": "heb", "hi": "hin", "hr": "hrv", "hu": "hun", "hy": "hye",
    "id": "ind", "is": "isl", "it": "ita", "ja": "jpn", "ka": "kat",
    "ko": "kor", "lt": "lit", "lv": "lav", "ms": "msa", "mt": "mlt",
    "nl": "nld", "no": "nor", "pl": "pol", "pt": "por", "ro": "ron",
    "ru": "rus", "sk": "slk", "sl": "slv", "sr": "srp", "sv": "swe",
    "sw": "swa", "ta": "tam", "te": "tel", "th": "tha", "tl": "tgl",
    "tr": "tur", "uk": "ukr", "ur": "urd", "vi": "vie", "zh": "zho",
}  # fmt: skip


def tvdb_language(tmdb_language: str) -> str | None:
    """The TVDB code for a TMDB language setting (`en-US` -> `eng`)."""
    if tmdb_language in _TVDB_REGIONAL_LANGUAGES:
        return _TVDB_REGIONAL_LANGUAGES[tmdb_language]
    return _TVDB_LANGUAGES.get(tmdb_language.split("-")[0].lower())


class TVDBClient:
    """
    Minimal TVDB v4 client (sync) used by the media-search pipeline.

    The third-party TVDB wrapper used by the project relied on ``urllib`` without
    passing a socket timeout. These clients keep the small endpoint surface we
    need, enforce a timeout on every request, and reuse one authenticated session
    for the lifetime of a media-search backend
    """

    BASE_URL = "https://api4.thetvdb.com/v4"
    # 50 pages of 500 is 25,000 episodes: a stop for a `links.next` that
    # never runs out, well past any real show
    _MAX_EPISODE_PAGES = 50

    def __init__(self, api_key: str, timeout: int) -> None:
        self.api_key = api_key
        self.timeout = max(1, timeout)
        self.session = new_http_session()
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

    def get_series_episodes(
        self, series_id: int, season_type: str, language: str | None = None
    ) -> dict[str, Any]:
        """One ordering's episodes; with `language`, names come translated.

        Without it TVDB names every episode in the series' original language
        (Japanese for most anime).

        TVDB serves 500 episodes a page, so a long show (One Piece runs past
        1,200) is read page by page until `links.next` runs out; the pages'
        episodes come back as one list under the first page's `data`.
        """
        path = f"/series/{series_id}/episodes/{season_type}"
        if language:
            path += f"/{quote(language, safe='')}"

        result: dict[str, Any] = {}
        episodes: list[Any] = []
        for page in range(self._MAX_EPISODE_PAGES):
            envelope = self._request_envelope(path, params={"page": str(page)})
            data = envelope.get("data")
            if not isinstance(data, dict):
                break
            if not result:
                result = cast(dict[str, Any], data)
            page_episodes = data.get("episodes")
            if not isinstance(page_episodes, list) or not page_episodes:
                break
            episodes.extend(cast(list[Any], page_episodes))
            links = envelope.get("links")
            if not isinstance(links, dict) or not links.get("next"):
                break
        if result:
            result["episodes"] = episodes
        return result

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
        return self._request_envelope(path, params)["data"]

    def _request_envelope(
        self, path: str, params: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        """The whole response body, for callers that need `links` too."""
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
        return cast(dict[str, Any], response_json)


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
        self, series_id: int, season_type: str, language: str | None = None
    ) -> dict[str, Any]:
        return await self._run(
            self.client.get_series_episodes,
            series_id,
            season_type,
            language,
        )

    async def _run(self, method: Any, *args: Any) -> Any:
        return await asyncio.wait_for(
            asyncio.to_thread(method, *args),
            timeout=self.timeout,
        )
