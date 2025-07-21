from datetime import datetime
from pathlib import Path
import pickle

import niquests
from pymediainfo import MediaInfo

from src.backend.trackers.utils import TRACKER_HEADERS
from src.backend.utils.resolution import VideoResolutionAnalyzer
from src.enums.trackers.torrentleech import TLCategories
from src.exceptions import TrackerError
from src.logger.nfo_forge_logger import LOG
from src.payloads.tracker_search_result import TrackerSearchResult

# TODO: implement full tv support


def tl_upload(
    announce_key: str,
    nfo: str,
    tracker_title: str | None,
    torrent_file: Path,
    mediainfo_obj: MediaInfo,
    timeout: int,
) -> str | None:
    uploader = TLUploader(announce_key=announce_key, timeout=timeout)
    return uploader.upload(
        nfo=nfo,
        tracker_title=tracker_title,
        torrent_file=torrent_file,
        mediainfo_obj=mediainfo_obj,
    )


class TLUploader:
    UPLOAD_URL: str = "https://www.torrentleech.org/torrents/upload/apiupload"

    def __init__(
        self,
        announce_key: str,
        timeout: int = 60,
    ):
        self.announce_key = announce_key
        self.timeout = timeout

    def upload(
        self,
        nfo: str,
        tracker_title: str | None,
        torrent_file: Path,
        mediainfo_obj: MediaInfo,
    ) -> str | None:
        files = self._get_files(nfo, torrent_file)
        get_resolution = VideoResolutionAnalyzer(mediainfo_obj).get_resolution()
        data = self._get_data(torrent_file.stem, get_resolution)
        if tracker_title:
            data["name"] = tracker_title

        LOG.info(LOG.LOG_SOURCE.BE, "Uploading torrent to TorrentLeech")
        LOG.debug(LOG.LOG_SOURCE.BE, f"TorrentLeech 'data': {data}")

        try:
            request = niquests.post(
                url=self.UPLOAD_URL,
                files=files,
                data=data,
                headers=TRACKER_HEADERS,
                timeout=self.timeout,
            )
            if request.ok and request.status_code == 200:
                request_text = request.text
                LOG.info(LOG.LOG_SOURCE.BE, f"Upload completed: {request_text}")
                return request_text
            else:
                upload_error_msg = (
                    "There was an error uploading to TorrentLeech: "
                    f"{request.status_code} ({request.reason} - {request.text})"
                )
                LOG.error(LOG.LOG_SOURCE.BE, upload_error_msg)
                raise TrackerError(upload_error_msg)
        except niquests.exceptions.RequestException as e:
            request_error_msg = f"There was an error uploading (niquests): {e}"
            LOG.error(LOG.LOG_SOURCE.BE, request_error_msg)
            raise TrackerError(request_error_msg)

    def _get_files(self, nfo: str, torrent_file: Path) -> dict:
        with open(torrent_file, "rb") as t_file:
            return {"nfo": nfo, "torrent": (str(torrent_file), t_file.read())}

    def _get_data(self, title: str, resolution: str) -> dict:
        return {
            "announcekey": self.announce_key,
            "category": self._detect_category(title, resolution),
        }

    @staticmethod
    def _detect_category(title: str, resolution: str) -> int:
        # TODO: This will still need some TLC. We need a cleaner way to determine whats what
        # and pass it to all trackers
        title_lowered = title.lower()
        if "bluray" in title_lowered or "blu-ray" in title_lowered:
            if resolution in {"720p", "1080p"}:
                return TLCategories.MOVIE_BLURAY_RIP.value
            elif resolution == "2160p":
                return TLCategories.MOVIE_4K.value
            else:
                raise TrackerError(
                    "Resolution must be one of '720p', '1080p' or '2160p'"
                )
        # TODO: will need to add check if it's a movie for SERIES
        elif "webrip" in title_lowered or "webdl" in title_lowered:
            return TLCategories.MOVIE_WEB_RIP.value
        elif "dvd" in title_lowered:
            if "rip" in title_lowered:
                return TLCategories.MOVIE_DVD_RIP.value
            return TLCategories.MOVIE_DVD.value
        elif "hdtv" in title_lowered:
            return TLCategories.MOVIE_HD_RIP.value
        else:
            raise TrackerError("Failed to determine proper TorrentLeech category")


class TLSearch:
    LOGIN_URL: str = "https://www.torrentleech.org/user/account/login/"
    SEARCH_URL: str = "https://www.torrentleech.org/torrents/browse/list/exact/1/query/{movie_title}/orderby/added/order/desc"
    TORRENT_URL: str = "https://www.torrentleech.me/torrent/{torrent_id}"

    def __init__(
        self,
        username: str,
        password: str,
        cookie_dir: Path,
        alt_2_fa_token: str | None,
        timeout: int = 60,
    ) -> None:
        self.username = username
        self.password = password
        self.cookie_path = cookie_dir / "tl_cookie.pkl"
        self.alt_2_fa_token = alt_2_fa_token
        self.timeout = timeout

        self._session = niquests.Session()

    def search(self, file_input: Path) -> list[TrackerSearchResult]:
        LOG.info(
            LOG.LOG_SOURCE.BE, f"Searching TorrentLeech for title: {file_input.stem}"
        )
        self._login()

        # if isinstance(file_input, Path):
        #     search_movie = self._search_movie(Path(file_input).stem)
        # else:
        #     search_movie = self._search_movie(file_input)
        results = []
        search_movie = self._search_movie(Path(file_input).stem)
        if search_movie:
            LOG.info(LOG.LOG_SOURCE.BE, f"Total results found: {len(search_movie)}")
            LOG.debug(LOG.LOG_SOURCE.BE, f"Total results found: {search_movie}")
            results = search_movie
        return results

    def _search_movie(self, file_input: str) -> list[TrackerSearchResult] | None:
        """
        Example output:
        [{'fid': '241265476', 'filename': 'Chaos.Theory.2007.REPACK.BluRay.1080p.DD.5.1.x264-BHDStudio.torrent',
        'name': 'Chaos Theory 2007 REPACK BluRay 1080p DD 5 1 x264-BHDStudio', 'addedTimestamp': '2024-04-22 00:13:12',
        'categoryID': 14, 'size': 5297940903, 'completed': 49, 'seeders': 23, 'leechers': 0, 'numComments': 0, 'tags':
        ['comedy', 'Drama', 'Romance'], 'new': False, 'imdbID': 'tt0460745', 'rating': 6.9, 'genres': 'Comedy, Drama,
        Romance', 'tvmazeID': '', 'igdbID': '', 'download_multiplier': 1, 'uploader': 'jlw4049'}]

        We convert the above with the sort_results method to a different format to be parsed in the UI
        """
        response = self._session.get(
            self.SEARCH_URL.format(movie_title=file_input), timeout=self.timeout
        )
        if response.ok and response.status_code == 200:
            results = response.json()["torrentList"]
            search_results = self._sort_results(results)
            return search_results
        else:
            raise TrackerError(
                f"Error searching for media. Status code: {response.status_code} Message: {response.content}"
            )

    def _sort_results(
        self, results_list: list[dict | None]
    ) -> list[TrackerSearchResult]:
        """Convert TL Torznab output to easily parse in the UI"""
        results = []
        for release in results_list:
            if release:
                result = TrackerSearchResult(
                    name=release.get("name"),
                    url=self.TORRENT_URL.format(torrent_id=release.get("fid")),
                    release_size=release.get("size"),
                    created_at=self._convert_date_time(release.get("addedTimestamp")),
                    seeders=release.get("seeders"),
                    leechers=release.get("leechers"),
                    grabs=release.get("completed"),
                    imdb_id=release.get("imdbID"),
                    uploader=release.get("uploader"),
                )
                results.append(result)
        return results

    @staticmethod
    def _convert_date_time(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    @staticmethod
    def _get_resolution(name: str) -> str:
        lowered_name = name.lower()
        if "720p" in lowered_name:
            return "720p"
        elif "1080p" in lowered_name:
            return "1080p"
        elif "2160p" in lowered_name:
            return "2160p"
        else:
            return ""

    def _login(self) -> bool:
        if self._load_cookies():
            try:
                cookie_token = self._validate_session()
                if cookie_token:
                    LOG.debug(
                        LOG.LOG_SOURCE.BE, "TorrentLeech cookies valid, skipping login"
                    )
                    return True
                else:
                    # cookie invalid/expired, delete and retry login
                    try:
                        self.cookie_path.unlink()
                        LOG.debug(
                            LOG.LOG_SOURCE.BE,
                            f"Deleted expired TorrentLeech cookie: {self.cookie_path}",
                        )
                    except Exception as e:
                        LOG.warning(
                            LOG.LOG_SOURCE.BE, f"Failed to delete expired cookie: {e}"
                        )
            except TrackerError as e:
                # cookie invalid/expired, delete and retry login
                try:
                    self.cookie_path.unlink()
                    LOG.debug(
                        LOG.LOG_SOURCE.BE,
                        f"Deleted expired TorrentLeech cookie (exception): {self.cookie_path}",
                    )
                except Exception as ex:
                    LOG.warning(
                        LOG.LOG_SOURCE.BE, f"Failed to delete expired cookie: {ex}"
                    )
                LOG.info(
                    LOG.LOG_SOURCE.BE,
                    f"TL cookie invalid: {e}. Retrying login with fresh session.",
                )

        response = self._session.get(self.LOGIN_URL, timeout=self.timeout)
        csrf_token = response.cookie["csrf_token"]

        data = {
            "username": self.username,
            "password": self.password,
            "csrf_token": csrf_token,
        }

        if self.alt_2_fa_token:
            data.update({"alt2FAToken": self.alt_2_fa_token})

        response = self._session.post(self.LOGIN_URL, data=data, timeout=self.timeout)
        if not response.ok:
            login_error_message = f"Failed to login to TorrentLeech. Status code: {response.status_code} Message: {response.content}"
            LOG.error(LOG.LOG_SOURCE.BE, login_error_message)
            raise TrackerError(login_error_message)

        if response.text and "loggedin" in response.text:
            LOG.debug(LOG.LOG_SOURCE.BE, "Successfully logged into TorrentLeech")
            self._save_cookies()
            return True
        return False

    def _validate_session(self) -> bool | None:
        """Perform a lightweight request to validate the session, if valid the required token is returned."""
        try:
            with self._session.get(self.LOGIN_URL) as response:
                if response.text and "loggedin" in response.text:
                    return True
        except niquests.RequestException:
            return False

    def _save_cookies(self) -> None:
        with open(self.cookie_path, "wb") as file:
            pickle.dump(self._session.cookies, file)
        LOG.debug(LOG.LOG_SOURCE.BE, f"TorrentLeech cookies saved: {self.cookie_path}")

    def _load_cookies(self) -> bool:
        if self.cookie_path.exists():
            with open(self.cookie_path, "rb") as file:
                cookies = pickle.load(file)
                self._session.cookies = cookies
            LOG.debug(
                LOG.LOG_SOURCE.BE,
                f"TorrentLeech cookies loaded from {self.cookie_path}",
            )
            return True
        LOG.debug(LOG.LOG_SOURCE.BE, "TorrentLeech cookies not found")
        return False
