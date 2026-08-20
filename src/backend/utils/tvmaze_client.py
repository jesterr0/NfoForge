from collections.abc import Mapping
import platform
import re
import time
from typing import Any

import niquests

from src.backend.utils.http_client import new_http_session
from src.logger.nfo_forge_logger import LOG
from src.version import __version__, program_name

# built here rather than imported from src.backend.trackers.utils: this module
# is a metadata provider, and importing the trackers package from
# src.backend.utils would invert the dependency (the TL uploader imports this).
TVMAZE_HEADERS = {
    "User-Agent": f"{program_name} v{__version__} ({platform.system()} {platform.release()})",
    "Accept": "application/json",
}

IMDB_ID_RE = re.compile(r"^tt\d{6,}$")


def normalize_imdb_id(imdb_id: str | None) -> str | None:
    """Return a canonical ``tt``-prefixed IMDb ID, or None when unusable.

    Callers hand us whatever the media-search pipeline resolved, which is
    normally already ``tt``-prefixed -- but a plugin-supplied payload can
    carry the bare digits, and TVmaze/TorrentLeech both reject that form.
    """
    if not imdb_id:
        return None
    candidate = str(imdb_id).strip().lower()
    if not candidate:
        return None
    if not candidate.startswith("tt"):
        candidate = f"tt{candidate}"
    return candidate if IMDB_ID_RE.match(candidate) else None


class TVmazeClient:
    """Minimal TVmaze client used to resolve TorrentLeech's tvmaze fields.

    TVmaze is free and keyless, so this needs none of the token handling the
    TVDB client carries. What it does need is to be harmless: every lookup
    here is an *enrichment* of an upload that is otherwise ready to go, so a
    TVmaze outage, a rate limit, or a show we simply can't match must never
    fail the upload. Every method returns None on any failure and logs why --
    the caller then omits the field and lets TorrentLeech auto-detect, which
    is exactly the behaviour we had before any of this existed.
    """

    BASE_URL = "https://api.tvmaze.com"
    # TVmaze publishes a rate limit (roughly 20 calls per 10s) and answers 429
    # once it is crossed; those, plus the usual gateway failures, are worth a
    # second look. A 404 is not -- it is a definitive "no match" answer.
    RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
    MAX_ATTEMPTS = 3
    RETRY_BACKOFF_SECONDS = 1.0

    def __init__(
        self, timeout: int = 60, session: niquests.Session | None = None
    ) -> None:
        self.timeout = max(1, timeout)
        self._session = session if session is not None else new_http_session()
        self._owns_session = session is None

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def lookup_show_id(
        self, imdb_id: str | None = None, tvdb_id: str | None = None
    ) -> int | None:
        """Resolve a TVmaze show ID from an IMDb or TVDB ID.

        Both are exact-ID lookups rather than a title search, so a hit is a
        genuine match and not a best guess -- which is the whole point, given
        a wrong ID is worse than none (it overrides the tracker's own
        detection with something incorrect).
        """
        candidates: tuple[tuple[str, str | None], ...] = (
            ("imdb", normalize_imdb_id(imdb_id)),
            ("thetvdb", self._numeric(tvdb_id)),
        )
        for param, value in candidates:
            if not value:
                continue
            payload = self._get("/lookup/shows", params={param: value})
            show_id = self._extract_id(payload)
            if show_id is not None:
                LOG.debug(
                    LOG.LOG_SOURCE.BE,
                    f"Resolved TVmaze show ID {show_id} via {param}={value}",
                )
                return show_id
            LOG.debug(LOG.LOG_SOURCE.BE, f"No TVmaze show matched {param}={value}")
        return None

    def get_episode_id(self, show_id: int, season: int, episode: int) -> int | None:
        """Resolve the TVmaze ID of one episode of a show.

        TorrentLeech distinguishes a show ID from an episode ID by way of its
        ``tvmazetype`` field, so a single-episode upload needs this rather
        than the show ID.
        """
        payload = self._get(
            f"/shows/{show_id}/episodebynumber",
            params={"season": str(season), "number": str(episode)},
        )
        episode_id = self._extract_id(payload)
        if episode_id is None:
            LOG.debug(
                LOG.LOG_SOURCE.BE,
                f"No TVmaze episode matched show {show_id} S{season:02d}E{episode:02d}",
            )
        return episode_id

    @staticmethod
    def _numeric(value: str | None) -> str | None:
        if not value:
            return None
        candidate = str(value).strip()
        return candidate if candidate.isdigit() else None

    @staticmethod
    def _extract_id(payload: Any) -> int | None:
        if not isinstance(payload, dict):
            return None
        raw_id = payload.get("id")
        if isinstance(raw_id, bool) or not isinstance(raw_id, int | str):
            return None
        try:
            return int(raw_id)
        except (TypeError, ValueError):
            return None

    def _get(self, path: str, params: Mapping[str, str] | None = None) -> Any | None:
        """GET a TVmaze endpoint, returning None rather than raising.

        A 404 from ``/lookup`` is TVmaze's documented "no match" answer, so it
        short-circuits instead of burning the remaining retries.
        """
        url = f"{self.BASE_URL}{path}"
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                with self._session.get(
                    url,
                    params=params,
                    headers=TVMAZE_HEADERS,
                    timeout=self.timeout,
                ) as response:
                    status_code = response.status_code
                    if status_code == 404:
                        return None
                    if response.ok:
                        return response.json()
                    if (
                        status_code in self.RETRY_STATUS_CODES
                        and attempt < self.MAX_ATTEMPTS
                    ):
                        LOG.debug(
                            LOG.LOG_SOURCE.BE,
                            f"TVmaze returned {status_code} for {path} "
                            f"(attempt {attempt}/{self.MAX_ATTEMPTS}), retrying",
                        )
                        time.sleep(self.RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    LOG.warning(
                        LOG.LOG_SOURCE.BE,
                        f"TVmaze request failed for {path}: {status_code}",
                    )
                    return None
            except niquests.exceptions.RequestException as error:
                if attempt < self.MAX_ATTEMPTS:
                    LOG.debug(
                        LOG.LOG_SOURCE.BE,
                        f"TVmaze request error for {path} "
                        f"(attempt {attempt}/{self.MAX_ATTEMPTS}): {error}, retrying",
                    )
                    time.sleep(self.RETRY_BACKOFF_SECONDS * attempt)
                    continue
                LOG.warning(
                    LOG.LOG_SOURCE.BE, f"TVmaze request error for {path}: {error}"
                )
                return None
            except (TypeError, ValueError) as error:
                LOG.warning(
                    LOG.LOG_SOURCE.BE, f"TVmaze returned an invalid response: {error}"
                )
                return None
        return None
