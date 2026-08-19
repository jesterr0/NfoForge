import os
from pathlib import Path
import re
from tempfile import mkstemp
from typing import Any
from urllib.parse import quote

import niquests
from niquests.typing import MultiPartFilesAltType
from pymediainfo import MediaInfo

from src.backend.trackers.utils import (
    DISC_TITLE_REGEX,
    TRACKER_HEADERS,
    looks_like_torrent,
    strip_title_dots,
)
from src.backend.upload_retry import classify_upload_post_error
from src.backend.utils.file_utilities import release_stem
from src.backend.utils.http_client import new_http_session
from src.backend.utils.media_info_utils import MinimalMediaInfo
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.hdb import HDBCategory, HDBCodec, HDBMedium
from src.exceptions import TrackerError
from src.logger.nfo_forge_logger import LOG
from src.payloads.tracker_search_result import TrackerSearchResult

_CODEC_FORMAT_MAP = {
    "AVC": HDBCodec.AVC,
    "HEVC": HDBCodec.HEVC,
    "VC-1": HDBCodec.VC1,
    "VP9": HDBCodec.VP9,
    "MPEG Video": HDBCodec.MPEG2,
    "MPEG-2 Video": HDBCodec.MPEG2,
    "MPEG-4 Visual": HDBCodec.XVID,
}


def hdb_category_id(media_type: MediaType, genre_names: tuple[str, ...] = ()) -> int:
    """HDBits requires this to resolve or refuses the upload/search."""
    if any(genre.strip().lower() == "documentary" for genre in genre_names):
        return HDBCategory.DOCUMENTARY.value
    if media_type is MediaType.MOVIE:
        return HDBCategory.MOVIE.value
    if media_type is MediaType.SERIES:
        return HDBCategory.TV.value
    raise TrackerError(f"HDBits does not support {media_type} uploads")


def hdb_codec_id(mediainfo_obj: MediaInfo) -> int:
    """HDBits requires this to resolve or refuses the upload/search."""
    video_format = None
    try:
        video_format = mediainfo_obj.video_tracks[0].format
    except (AttributeError, IndexError, TypeError):
        video_format = None
    codec = _CODEC_FORMAT_MAP.get(str(video_format))
    if codec is None:
        raise TrackerError(
            f"Failed to determine HDBits 'Codec ID' for video format {video_format!r}"
        )
    return codec.value


def hdb_medium_id(input_path: Path) -> int:
    """HDBits requires this to resolve or refuses the upload/search."""
    title_lowered = release_stem(input_path).lower()
    title_lowered_strip_periods = title_lowered.replace(".", "")

    if "remux" in title_lowered:
        return HDBMedium.REMUX.value

    if DISC_TITLE_REGEX.search(title_lowered):
        return HDBMedium.BLURAY.value

    if "web" in title_lowered:
        if re.search(r"\bweb[._ -]?dl\b", title_lowered):
            return HDBMedium.WEBDL.value
        if re.search(r"\bweb[._ -]?rip\b", title_lowered):
            return HDBMedium.ENCODE.value

    if "hdtv" in title_lowered or "hd-tv" in title_lowered:
        return HDBMedium.CAPTURE.value

    if any(
        codec in title_lowered_strip_periods
        for codec in ("h264", "x264", "h265", "x265")
    ):
        return HDBMedium.ENCODE.value

    raise TrackerError("Failed to determine HDBits 'Medium ID'")


def hdb_uploader(
    username: str,
    passkey: str,
    session_cookie: str,
    torrent_file: Path,
    input_path: Path,
    media_type: MediaType,
    mediainfo_obj: MediaInfo,
    tracker_title: str | None,
    nfo: str,
    imdb_id: str | None = None,
    tvdb_id: str | None = None,
    genre_names: tuple[str, ...] = (),
    internal: bool = False,
    season_number: int | None = None,
    episode_number: int | None = None,
    season_pack: bool = False,
    timeout: int = 60,
) -> bool | None:
    uploader = HDBUploader(
        username=username,
        passkey=passkey,
        session_cookie=session_cookie,
        torrent_file=torrent_file,
        input_path=input_path,
        media_type=media_type,
        mediainfo_obj=mediainfo_obj,
        timeout=timeout,
    )
    return uploader.upload(
        tracker_title=tracker_title,
        nfo=nfo,
        imdb_id=imdb_id,
        tvdb_id=tvdb_id,
        genre_names=genre_names,
        internal=internal,
        season_number=season_number,
        episode_number=episode_number,
        season_pack=season_pack,
    )


class HDBUploader:
    """HDBits uploader.

    HDBits' JSON API (``/api/torrents``, ``/api/test``) authenticates with a
    username+passkey pair, but the actual upload form (``/upload/upload``)
    requires a logged-in browser session cookie -- HDBits has no supported
    automated-login path (its login page can serve a captcha), so every
    existing HDB uploader tool has the user paste an already-obtained
    session cookie rather than attempting a login. NfoForge does the same.
    """

    UPLOAD_URL = f"{TrackerSelection.HDB.get_root_url()}upload/upload"
    API_URL = f"{TrackerSelection.HDB.get_root_url()}api/torrents"
    DOWNLOAD_URL = f"{TrackerSelection.HDB.get_root_url()}download.php"
    ROOT_URL = TrackerSelection.HDB.get_root_url()

    __slots__ = (
        "username",
        "passkey",
        "torrent_file",
        "input_path",
        "media_type",
        "mediainfo_obj",
        "timeout",
        "_session",
    )

    def __init__(
        self,
        username: str,
        passkey: str,
        session_cookie: str,
        torrent_file: Path,
        input_path: Path,
        media_type: MediaType,
        mediainfo_obj: MediaInfo,
        timeout: int = 60,
    ) -> None:
        self.username = username
        self.passkey = passkey
        self.torrent_file = torrent_file
        self.input_path = input_path
        self.media_type = media_type
        self.mediainfo_obj = mediainfo_obj
        self.timeout = timeout

        self._session = new_http_session()
        self._load_session_cookie(session_cookie)

    def _load_session_cookie(self, session_cookie: str) -> None:
        """Parse a raw ``name=value; name2=value2`` cookie-header string."""
        for part in session_cookie.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            name, _, value = part.partition("=")
            name = name.strip()
            value = value.strip()
            if not name:
                continue
            self._session.cookies.set(name, value, domain="hdbits.org", path="/")

    def validate_cookies(self) -> bool:
        try:
            response = self._session.get(
                self.ROOT_URL, headers=TRACKER_HEADERS, timeout=self.timeout
            )
        except niquests.exceptions.RequestException as error:
            raise TrackerError(
                f"Failed to validate HDBits session cookie: {error}"
            ) from error
        return bool(response.text) and (
            '<a href="/logout.php">Logout</a>' in response.text
        )

    def upload(
        self,
        tracker_title: str | None,
        nfo: str,
        imdb_id: str | None = None,
        tvdb_id: str | None = None,
        genre_names: tuple[str, ...] = (),
        internal: bool = False,
        season_number: int | None = None,
        episode_number: int | None = None,
        season_pack: bool = False,
    ) -> bool | None:
        if self.media_type is MediaType.MOVIE and not imdb_id:
            raise TrackerError("HDBits requires an IMDb id for movie uploads")
        if self.media_type is MediaType.SERIES and not imdb_id and not tvdb_id:
            raise TrackerError("HDBits requires an IMDb or TVDB id for TV uploads")

        if not self.validate_cookies():
            raise TrackerError(
                "HDBits session cookie is missing or has expired. Paste a "
                "fresh session cookie in HDBits tracker settings and try again."
            )

        category_id = hdb_category_id(self.media_type, genre_names)
        codec_id = hdb_codec_id(self.mediainfo_obj)
        medium_id = hdb_medium_id(self.input_path)

        upload_payload: dict[str, Any] = {
            "name": tracker_title
            if tracker_title
            else self.generate_release_title(release_stem(self.input_path)),
            "category": category_id,
            "codec": codec_id,
            "medium": medium_id,
            "origin": int(internal),
            "descr": nfo,
            "techinfo": MinimalMediaInfo(self.input_path).get_full_mi_str(
                cleansed=True
            ),
        }
        if imdb_id:
            upload_payload["imdb"] = f"https://www.imdb.com/title/{imdb_id}/"
        else:
            upload_payload["imdb"] = 0
        if self.media_type is MediaType.SERIES and tvdb_id:
            upload_payload["tvdb"] = tvdb_id
            if season_number is not None:
                upload_payload["tvdb_season"] = season_number
            if not season_pack and episode_number is not None:
                upload_payload["tvdb_episode"] = episode_number

        LOG.debug(LOG.LOG_SOURCE.BE, f"HDBits payload: {upload_payload}")

        try:
            with self.torrent_file.open("rb") as torrent_fh:
                files: MultiPartFilesAltType = {
                    "file": (
                        self.torrent_file.name,
                        torrent_fh.read(),
                        "application/x-bittorrent",
                    )
                }
                response = self._session.post(
                    self.UPLOAD_URL,
                    data=upload_payload,
                    files=files,
                    headers=TRACKER_HEADERS,
                    timeout=self.timeout,
                )
        except niquests.exceptions.RequestException as error:
            upload_error_msg = f"Failed to upload to HDBits: {error}"
            LOG.error(LOG.LOG_SOURCE.BE, upload_error_msg)
            retryable, server_accepted = classify_upload_post_error(error)
            raise TrackerError(
                upload_error_msg,
                retryable=retryable,
                server_accepted=server_accepted,
            ) from error

        response_url = str(response.url) if response.url else ""
        match = re.match(
            r".*?hdbits\.org/details\.php\?id=(\d+)&uploaded=(\d+)", response_url
        )
        if not match:
            status_code = response.status_code
            response_error_msg = (
                f"Failed to upload torrent to HDBits. Result URL {response_url} "
                f"({status_code}) was not the expected one."
            )
            LOG.error(LOG.LOG_SOURCE.BE, response_error_msg)
            # 408/429 mean the request was rejected before it could be
            # processed. A 5xx means HDBits received and answered the
            # upload -- it may have recorded the torrent before failing, so
            # that must route to the user instead of an automatic retry.
            # A non-matching 200 means the form was rejected outright
            # (nothing was recorded), same convention as every other
            # uploader in this codebase.
            retryable = isinstance(status_code, int) and (
                status_code == 408 or status_code == 429 or status_code >= 500
            )
            server_accepted = isinstance(status_code, int) and status_code >= 500
            raise TrackerError(
                response_error_msg,
                retryable=retryable,
                server_accepted=server_accepted,
                status_code=status_code if isinstance(status_code, int) else None,
            )

        hdb_id = match.group(1)
        LOG.info(LOG.LOG_SOURCE.BE, f"Successfully uploaded to HDBits: id={hdb_id}")
        self._download_new_torrent(hdb_id)
        return True

    def _download_new_torrent(self, hdb_id: str) -> Path:
        """Fetch the tracker-issued, passkey-stamped .torrent after upload."""
        try:
            info_response = self._session.post(
                self.API_URL,
                json={
                    "username": self.username,
                    "passkey": self.passkey,
                    "id": hdb_id,
                },
                headers=TRACKER_HEADERS,
                timeout=self.timeout,
            )
            info_response.raise_for_status()
            info_json = info_response.json()
            filename = info_json["data"][0]["filename"]
        except (
            niquests.exceptions.RequestException,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as error:
            raise TrackerError(
                f"Uploaded to HDBits but failed to look up the new torrent's "
                f"filename: {error}",
                retryable=True,
                server_accepted=True,
                phase="download",
            ) from error

        destination = self.torrent_file
        destination.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = mkstemp(
            prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "wb") as torrent_file:
                with self._session.get(
                    f"{self.DOWNLOAD_URL}/{quote(filename)}",
                    params={"passkey": self.passkey, "id": hdb_id},
                    headers=TRACKER_HEADERS,
                    timeout=self.timeout,
                    stream=True,
                ) as response:
                    response.raise_for_status()
                    response_headers = dict(response.headers)
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            torrent_file.write(chunk)

            content = temporary_path.read_bytes()
            if not looks_like_torrent(content, response_headers):
                raise TrackerError(
                    "Downloaded file from HDBits is not a valid torrent",
                    retryable=True,
                    server_accepted=True,
                    phase="download",
                )
            temporary_path.replace(destination)
            return destination
        except (niquests.exceptions.RequestException, OSError) as error:
            raise TrackerError(
                f"Failed to download the new torrent from HDBits: {error}",
                retryable=True,
                server_accepted=True,
                phase="download",
            ) from error
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def generate_release_title(release_title: str) -> str:
        name = strip_title_dots(release_title)
        name = re.sub(r"\bH\s?265\b", "HEVC", name)
        name = re.sub(r"(?<!\S)DV(?!\S)", "DoVi", name)
        if "HDR10+" not in name:
            name = re.sub(r"(?<!\S)HDR(?!\S)", "HDR10", name)
        name = name.replace("REMUX", "Remux")
        name = re.sub(r"[^0-9a-zA-ZÀ-ÿ. :&+'\-\[\]]+", "", name)
        name = name.replace(" .", ".").replace("..", ".")
        return name


_HDB_SEARCH_SESSION = new_http_session()


class HDBSearch:
    """Search HDBits utilizing their JSON API."""

    __slots__ = ("username", "passkey", "timeout")

    API_URL = f"{TrackerSelection.HDB.get_root_url()}api/torrents"
    DETAILS_URL = f"{TrackerSelection.HDB.get_root_url()}details.php?id={{id}}"

    def __init__(self, username: str, passkey: str, timeout: int = 60) -> None:
        self.username = username
        self.passkey = passkey
        self.timeout = timeout

    def search(
        self,
        input_path: Path,
        media_type: MediaType,
        mediainfo_obj: MediaInfo | None = None,
        imdb_id: str | None = None,
        tvdb_id: str | None = None,
        genre_names: tuple[str, ...] = (),
    ) -> list[TrackerSearchResult]:
        payload: dict[str, Any] = {
            "username": self.username,
            "passkey": self.passkey,
        }

        # Category/codec/medium are best-effort here: search should still
        # work with whatever it can derive rather than aborting outright.
        try:
            payload["category"] = hdb_category_id(media_type, genre_names)
        except TrackerError:
            pass
        if mediainfo_obj is not None:
            try:
                payload["codec"] = hdb_codec_id(mediainfo_obj)
            except TrackerError:
                pass
        try:
            payload["medium"] = hdb_medium_id(input_path)
        except TrackerError:
            pass

        if imdb_id:
            payload["imdb"] = {"id": imdb_id.replace("tt", "")}
        elif tvdb_id:
            payload["tvdb"] = {"id": tvdb_id}
        else:
            payload["search"] = release_stem(input_path)

        results: list[TrackerSearchResult] = []
        try:
            LOG.info(
                LOG.LOG_SOURCE.BE, f"Searching HDBits for release: {input_path.name}"
            )
            response = _HDB_SEARCH_SESSION.post(
                self.API_URL,
                json=payload,
                headers=TRACKER_HEADERS,
                timeout=self.timeout,
            )
            response_json = response.json()
            results = self._convert_response(response_json.get("data", []))
            LOG.info(LOG.LOG_SOURCE.BE, f"Total results found: {len(results)}")
            LOG.debug(LOG.LOG_SOURCE.BE, f"Total results found: {results}")
        except niquests.exceptions.RequestException as error_message:
            raise TrackerError(str(error_message)) from error_message

        return results

    def _convert_response(
        self, data: list[dict[str, Any]]
    ) -> list[TrackerSearchResult]:
        results: list[TrackerSearchResult] = []
        for release in data:
            release_id = release.get("id")
            result = TrackerSearchResult(
                name=release.get("name"),
                url=self.DETAILS_URL.format(id=release_id) if release_id else None,
                release_size=release.get("size"),
                files=release.get("filecount"),
                imdb_id=str(release["imdb"]["id"])
                if isinstance(release.get("imdb"), dict) and release["imdb"].get("id")
                else None,
                info_hash=release.get("hash"),
            )
            results.append(result)
        return results
