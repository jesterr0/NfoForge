import re

# import regex
import requests

from datetime import datetime

from pathlib import Path

from src.logger.nfo_forge_logger import LOG

# from src.enums.media_mode import MediaMode
from src.exceptions import TrackerError
from src.backend.trackers.utils import TRACKER_HEADERS

# from src.backend.utils.media_info_utils import MinimalMediaInfo
from src.payloads.tracker_search_result import TrackerSearchResult


class ReelFlixSearch:
    """
    Search ReelFliX utilizing their API

    API: https://github.com/HDInnovations/UNIT3D-Community-Edition/wiki/Torrent-API-(UNIT3D-v8.3.4)
    """

    SEARCH_URL = "https://reelflix.xyz/api/torrents/filter"

    def __init__(self, api_key: str, timeout: int = 60) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def search(self, file_name: str) -> list[TrackerSearchResult]:
        params = {
            "api_token": self.api_key,
            "file_name": file_name,
            "perPage": 50,
        }

        results = None
        try:
            LOG.info(LOG.LOG_SOURCE.BE, f"Searching ReelFliX for title: {file_name}")
            with requests.get(
                self.SEARCH_URL,
                headers=TRACKER_HEADERS,
                params=params,
                timeout=self.timeout,
            ) as response:
                if response.ok and response.status_code == 200:
                    response_json = response.json()
                    results = self._convert_response(response_json)
        except requests.exceptions.RequestException as error_message:
            raise TrackerError(error_message)

        results = results if results else []
        LOG.info(LOG.LOG_SOURCE.BE, f"Total results found: {len(results)}")
        LOG.debug(LOG.LOG_SOURCE.BE, f"Total results found: {results}")
        return results

    def _convert_response(self, data: dict | None) -> list[TrackerSearchResult]:
        results = []
        if data:
            for item in data.get("data", []):
                if item:
                    attributes = item.get("attributes", {})
                    if attributes:
                        result = TrackerSearchResult(
                            name=attributes.get("name"),
                            url=attributes.get("details_link"),
                            download_link=attributes.get("download_link"),
                            release_type=attributes.get("type"),
                            release_size=attributes.get("size"),
                            created_at=self._handle_date(attributes.get("created_at")),
                            seeders=attributes.get("seeders"),
                            leechers=attributes.get("leechers"),
                            grabs=attributes.get("times_completed"),
                            files=len(attributes.get("files", [])),
                            imdb_id=attributes.get("imdb_id"),
                            tmdb_id=attributes.get("tmdb_id"),
                            uploader=attributes.get("uploader"),
                            info_hash=attributes.get("info_hash"),
                        )
                        results.append(result)
        return results

    @staticmethod
    def _handle_date(timestamp: str | None) -> datetime | None:
        if timestamp:
            return datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
        return timestamp if timestamp else None
