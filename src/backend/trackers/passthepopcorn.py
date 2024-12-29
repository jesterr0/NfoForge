import json
import requests


# TODO: get this from the included module (src.backend.trackers.utils)
import platform

# from src.version import program_name, __version__

TRACKER_HEADERS = {
    "User-Agent": f"NfoForge v0.4.4 ({platform.system()} {platform.release()})"
}

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class TrackerSearchResult:
    name: str | None = None
    url: str | None = None
    download_link: str | None = None
    release_type: str | None = None
    release_size: int | None = None
    created_at: datetime | None = None
    seeders: int | None = None
    leechers: int | None = None
    grabs: int | None = None
    files: int | None = None
    imdb_id: str | None = None
    tmdb_id: str | None = None
    uploader: str | None = None
    info_hash: str | None = None


# class PTPUploader:
#     URL = "https://passthepopcorn.me/torrents.php"

#     def __init__(self) -> None:
#         self._session = requests.Session()


class PTPSearch:
    """Search PassThePopcorn"""

    URL = "https://passthepopcorn.me/torrents.php"

    def __init__(self, api_user: str, api_key: str, timeout: int = 60) -> None:
        self.api_user = api_user
        self.api_key = api_key
        self.timeout = timeout

    def search(
        self,
        movie_title: str,
        movie_year: int,
        file_name: str,
        imdb_id: str | None = None,
    ) -> list[TrackerSearchResult | None]:
        results = []

        headers = {
            "ApiUser": self.api_user,
            "ApiKey": self.api_key,
            "User-Agent": TRACKER_HEADERS["User-Agent"],
        }
        params = {
            "searchstr": movie_title,
            "year": movie_year,
            "noredirect": 1,
            "action": "advanced",
        }
        if imdb_id:
            params["searchstr"] = imdb_id
        if file_name:
            params["filelist"] = file_name

        # LOG.info(LOG.LOG_SOURCE.BE, f"Searching BeyondHD for title: {title}")
        try:
            response = requests.get(
                self.URL, headers=headers, params=params, timeout=self.timeout
            )
            if response.ok and response.status_code == 200:
                response_json = response.json()
                movies: list[dict] = response_json.get("Movies", [])
                for torrent in movies:
                    for movie_file in torrent.get("Torrents", []):
                        for item in movie_file.get("FileList", []):
                            path_name = item.get("Path", "")
                            if path_name == file_name:
                                group_id = torrent.get("GroupId")
                                movie_id = movie_file.get("Id")
                                link = (
                                    f"{self.URL}?id={group_id}&torrentid={movie_id}"
                                    if group_id and movie_id
                                    else None
                                )
                                result = TrackerSearchResult(
                                    name=path_name,
                                    url=link,
                                    release_size=item.get("Size"),
                                    created_at=torrent.get("LastUploadTime"),
                                    seeders=torrent.get("TotalSeeders"),
                                    leechers=torrent.get("TotalLeechers"),
                                    grabs=torrent.get("TotalSnatched"),
                                    files=len(movie_file.get("FileList", [])),
                                    imdb_id=f'tt{torrent.get("ImdbId")}'
                                    if torrent.get("ImdbId")
                                    else None,
                                )
                                results.append(result)

            return results
        except requests.exceptions.RequestException as error_message:
            raise
            # raise TrackerError(error_message)
