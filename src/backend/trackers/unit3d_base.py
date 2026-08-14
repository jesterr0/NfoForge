from datetime import datetime
from enum import Enum
import os
from pathlib import Path
import re
from tempfile import mkstemp
from typing import Any, BinaryIO, TypeAlias
from urllib.parse import urlparse

import niquests
from niquests.typing import MultiPartFilesAltType
from pymediainfo import MediaInfo
from tenacity import Retrying, retry_if_exception, stop_after_attempt
from tenacity.wait import wait_exponential

from src.backend.trackers.utils import (
    API_TRACKER_HEADERS,
    DISC_TITLE_REGEX,
    TRACKER_HEADERS,
    looks_like_torrent,
    strip_title_dots,
)
from src.backend.upload_retry import RETRY_ATTEMPTS, classify_upload_post_error
from src.backend.utils.file_utilities import release_stem
from src.backend.utils.media_info_utils import MinimalMediaInfo
from src.backend.utils.resolution import VideoResolutionAnalyzer
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.aither import AitherCategory, AitherResolution, AitherType
from src.enums.trackers.blutopia import (
    BlutopiaCategory,
    BlutopiaResolution,
    BlutopiaType,
)
from src.enums.trackers.darkpeers import (
    DarkPeersCategory,
    DarkPeersResolution,
    DarkPeersType,
)
from src.enums.trackers.fearnopeer import (
    FearNoPeerCategory,
    FearNoPeerResolution,
    FearNoPeerType,
)
from src.enums.trackers.huno import HunoCategory, HunoResolution, HunoType
from src.enums.trackers.lst import LSTCategory, LSTResolution, LSTType
from src.enums.trackers.onlyencodes import (
    OnlyEncodesCategory,
    OnlyEncodesResolution,
    OnlyEncodesType,
)
from src.enums.trackers.reelflix import (
    ReelFlixCategory,
    ReelFlixResolution,
    ReelFlixType,
)
from src.enums.trackers.seedpool import (
    SeedPoolCategory,
    SeedPoolResolution,
    SeedPoolType,
)
from src.enums.trackers.shareisland import (
    ShareIslandCategory,
    ShareIslandResolution,
    ShareIslandType,
)
from src.enums.trackers.uploadcx import (
    UploadCXCategory,
    UploadCXResolution,
    UploadCXType,
)
from src.enums.trackers.utp import UTPCategory, UTPResolution, UTPType
from src.enums.trackers.yuscene import (
    YuSceneCategory,
    YuSceneResolution,
    YuSceneType,
)
from src.exceptions import TrackerError
from src.logger.nfo_forge_logger import LOG
from src.payloads.tracker_search_result import TrackerSearchResult

CategoryEnums: TypeAlias = (
    ReelFlixCategory
    | AitherCategory
    | HunoCategory
    | LSTCategory
    | DarkPeersCategory
    | ShareIslandCategory
    | UploadCXCategory
    | OnlyEncodesCategory
    | BlutopiaCategory
    | SeedPoolCategory
    | UTPCategory
    | YuSceneCategory
    | FearNoPeerCategory
)
ResolutionEnums: TypeAlias = (
    ReelFlixResolution
    | AitherResolution
    | HunoResolution
    | LSTResolution
    | DarkPeersResolution
    | ShareIslandResolution
    | UploadCXResolution
    | OnlyEncodesResolution
    | BlutopiaResolution
    | SeedPoolResolution
    | UTPResolution
    | YuSceneResolution
    | FearNoPeerResolution
)
TypeEnums: TypeAlias = (
    ReelFlixType
    | AitherType
    | HunoType
    | LSTType
    | DarkPeersType
    | ShareIslandType
    | UploadCXType
    | OnlyEncodesType
    | BlutopiaType
    | SeedPoolType
    | UTPType
    | YuSceneType
    | FearNoPeerType
)


class Unit3dBaseUploader:
    """API: https://github.com/HDInnovations/UNIT3D/blob/master/book/src/torrent_api.md"""

    __slots__ = (
        "tracker_name",
        "upload_url",
        "base_url",
        "media_type",
        "api_key",
        "torrent_file",
        "input_path",
        "mediainfo_obj",
        "cat_enum",
        "res_enum",
        "type_enum",
        "timeout",
    )

    # TODO: when adding DISC support we'll need to add region_ids and distributor_ids

    def __init__(
        self,
        tracker_name: TrackerSelection,
        base_url: str,
        media_type: MediaType,
        api_key: str,
        torrent_file: Path,
        input_path: Path,
        mediainfo_obj: MediaInfo,
        cat_enum: type[Enum],
        res_enum: type[Enum],
        type_enum: type[Enum],
        timeout: int = 60,
    ) -> None:
        self.tracker_name = tracker_name
        self.base_url = cleanse_base_url(base_url)
        self.upload_url = f"{self.base_url}/api/torrents/upload"
        self.media_type = media_type
        self.api_key = api_key
        self.torrent_file = torrent_file
        self.input_path = input_path
        self.mediainfo_obj = mediainfo_obj
        self.timeout = timeout

        # assign enums based on child
        self.cat_enum = cat_enum
        self.res_enum = res_enum
        self.type_enum = type_enum

    def upload(
        self,
        tracker_title: str | None,
        imdb_id: str | None = None,
        tmdb_id: str | None = None,
        tvdb_id: str | None = None,
        mal_id: str | None = None,
        nfo: str | None = None,
        internal: bool = False,
        anonymous: bool = False,
        personal_release: bool | None = True,
        stream_optimized: bool = False,
        opt_in_to_mod_queue: bool | None = False,
        draft_queue_opt_in: bool | None = False,
        featured: bool | None = False,
        free: bool | int | None = False,
        double_up: bool | None = False,
        sticky: bool | None = False,
        season_number: int | None = None,
        episode_number: int | None = None,
        episode_number_end: int | None = None,
        season_pack: bool = False,
    ) -> bool | None:
        params = {"api_token": self.api_key}
        upload_payload = self._build_upload_payload(
            tracker_title=tracker_title,
            imdb_id=imdb_id,
            tmdb_id=tmdb_id,
            tvdb_id=tvdb_id,
            mal_id=mal_id,
            nfo=nfo,
            internal=internal,
            anonymous=anonymous,
            personal_release=personal_release,
            stream_optimized=stream_optimized,
            opt_in_to_mod_queue=opt_in_to_mod_queue,
            draft_queue_opt_in=draft_queue_opt_in,
            featured=featured,
            free=free,
            double_up=double_up,
            sticky=sticky,
            season_number=season_number,
            episode_number=episode_number,
            episode_number_end=episode_number_end,
            season_pack=season_pack,
        )

        response_context: Any = None
        try:
            with self.torrent_file.open(mode="rb") as open_torrent:
                request_data, request_files = self._prepare_upload_request(
                    upload_payload, open_torrent
                )
                LOG.debug(
                    LOG.LOG_SOURCE.BE,
                    f"{self.tracker_name} payload: {request_data}",
                )
                with niquests.post(
                    url=self.upload_url,
                    files=request_files,
                    params=params,
                    data=request_data,
                    headers=API_TRACKER_HEADERS,
                    timeout=self.timeout,
                ) as response:
                    response_json = response.json()
                    # {'success': True, 'data': 'https://baseurl/torrent/download/45835.keydata', 'message': 'Torrent uploaded successfully.'}
                    message = response_json.get("message")
                    context = response_json.get("data")
                    if (
                        response_json.get("success") is True
                        and isinstance(message, str)
                        and "successfully" in message
                    ):
                        response_context = context
                    else:
                        error_msg = f"Message='{message}' Context='{context}'"
                        status_code = getattr(response, "status_code", None)
                        # 408/429 mean the request was rejected before it
                        # could be processed. A 5xx means the tracker
                        # received and answered the upload -- it may have
                        # recorded the torrent before failing, so that must
                        # route to the user instead of an automatic retry.
                        retryable = isinstance(status_code, int) and (
                            status_code == 408
                            or status_code == 429
                            or status_code >= 500
                        )
                        server_accepted = (
                            isinstance(status_code, int) and status_code >= 500
                        )
                        raise TrackerError(
                            error_msg,
                            retryable=retryable,
                            server_accepted=server_accepted,
                            status_code=(
                                status_code if isinstance(status_code, int) else None
                            ),
                        )

            # The source torrent must be closed before replacing it on Windows.
            download_url = self._resolve_uploaded_torrent_download_url_with_retry(
                response_context
            )
            self._download_uploaded_torrent_with_retry(download_url)
            return True
        except TrackerError as error:
            requests_exc_error_msg = f"Failed to upload to {self.tracker_name}: {error}"
            LOG.error(LOG.LOG_SOURCE.BE, requests_exc_error_msg)
            raise TrackerError(
                requests_exc_error_msg,
                retryable=error.retryable,
                server_accepted=error.server_accepted,
                phase=error.phase,
                status_code=error.status_code,
            ) from error
        except niquests.exceptions.RequestException as error:
            requests_exc_error_msg = f"Failed to upload to {self.tracker_name}: {error}"
            LOG.error(LOG.LOG_SOURCE.BE, requests_exc_error_msg)
            retryable, server_accepted = classify_upload_post_error(error)
            raise TrackerError(
                requests_exc_error_msg,
                retryable=retryable,
                server_accepted=server_accepted,
            ) from error

    def _prepare_upload_request(
        self, upload_payload: dict[str, Any], open_torrent: BinaryIO
    ) -> tuple[dict[str, Any], MultiPartFilesAltType]:
        """Return the form fields and files for one UNIT3D upload.

        Most UNIT3D sites accept description and MediaInfo as ordinary form
        fields. Trackers whose API diverges can override this hook without
        changing the wire format used by every sibling tracker.
        """
        return upload_payload, {"torrent": open_torrent}

    def _resolve_uploaded_torrent_download_url(self, context: Any) -> str:
        """Extract the registered-torrent URL from a successful response."""
        if isinstance(context, str) and context:
            return context
        raise TrackerError(
            "Tracker did not return a torrent download URL",
            retryable=False,
            server_accepted=True,
            phase="download",
        )

    def _resolve_uploaded_torrent_download_url_with_retry(self, context: Any) -> str:
        """Resolve an artifact URL without ever repeating the upload POST."""
        return Retrying(
            retry=retry_if_exception(
                lambda error: (
                    isinstance(error, TrackerError)
                    and bool(getattr(error, "server_accepted", False))
                    and bool(getattr(error, "retryable", False))
                )
            ),
            stop=stop_after_attempt(RETRY_ATTEMPTS),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
            reraise=True,
        )(lambda: self._resolve_uploaded_torrent_download_url(context))

    def _download_uploaded_torrent(self, download_url: str) -> Path:
        """Stream the tracker-generated torrent to its final path atomically."""
        # By the time this method runs, the tracker has already accepted the
        # upload (`upload()` only calls it after a successful response), so
        # every error raised here must carry `server_accepted=True,
        # phase="download"` -- exactly like the two sibling raises below --
        # or the UI's duplicate-upload safeguard never engages and a retry
        # re-POSTs the whole upload to a tracker that already has it.
        parsed_download_url = urlparse(download_url)
        if parsed_download_url.scheme not in ("https", "http"):
            raise TrackerError(
                f"{self.tracker_name} returned a download URL with an "
                "unsupported scheme",
                retryable=False,
                server_accepted=True,
                phase="download",
            )
        # `upload_url` is derived from the same `base_url` the tracker was
        # configured with, so its host is what a legitimate download URL
        # should share. Refuse a response pointing somewhere else.
        expected_host = urlparse(self.upload_url).hostname
        if expected_host and parsed_download_url.hostname != expected_host:
            raise TrackerError(
                f"{self.tracker_name} returned a download URL for an "
                f"unexpected host ({parsed_download_url.hostname!r}, "
                f"expected {expected_host!r})",
                retryable=False,
                server_accepted=True,
                phase="download",
            )

        destination = self.torrent_file
        destination.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = mkstemp(
            prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "wb") as torrent_file:
                with niquests.get(
                    download_url,
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
                    "Downloaded file is not a valid torrent",
                    retryable=True,
                    server_accepted=True,
                    phase="download",
                )
            temporary_path.replace(destination)
            return destination
        except (niquests.exceptions.RequestException, OSError) as error:
            raise TrackerError(
                f"Failed to download torrent from {self.tracker_name}: {error}",
                retryable=True,
                server_accepted=True,
                phase="download",
            ) from error
        finally:
            temporary_path.unlink(missing_ok=True)

    def _download_uploaded_torrent_with_retry(self, download_url: str) -> Path:
        """Retry artifact download without POSTing the upload again."""
        return Retrying(
            retry=retry_if_exception(
                lambda error: (
                    isinstance(error, TrackerError)
                    and bool(getattr(error, "server_accepted", False))
                    and bool(getattr(error, "retryable", False))
                )
            ),
            stop=stop_after_attempt(RETRY_ATTEMPTS),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
            reraise=True,
        )(lambda: self._download_uploaded_torrent(download_url))

    def _build_upload_payload(
        self,
        tracker_title: str | None,
        imdb_id: str | None = None,
        tmdb_id: str | None = None,
        tvdb_id: str | None = None,
        mal_id: str | None = None,
        nfo: str | None = None,
        internal: bool = False,
        anonymous: bool = False,
        personal_release: bool | None = True,
        stream_optimized: bool = False,
        opt_in_to_mod_queue: bool | None = False,
        draft_queue_opt_in: bool | None = False,
        featured: bool | None = False,
        free: bool | int | None = False,
        double_up: bool | None = False,
        sticky: bool | None = False,
        season_number: int | None = None,
        episode_number: int | None = None,
        episode_number_end: int | None = None,
        season_pack: bool = False,
    ) -> dict[str, Any]:
        upload_payload: dict[str, Any] = {
            # applied to a supplied title as well, not only to the filename
            # fallback -- a title edited in the overview dialog would otherwise
            # ship its periods verbatim, which is not what that dialog promises
            "name": self.generate_release_title(
                tracker_title if tracker_title else release_stem(self.input_path)
            ),
            "description": nfo,
            "mediainfo": MinimalMediaInfo(self.input_path).get_full_mi_str(
                cleansed=True
            ),
            # 'bdinfo': bd_dump,
            "category_id": self._get_category_id(),
            "type_id": self._get_type_id(),
            "resolution_id": self._get_resolution_id(),
            "anonymous": int(anonymous),
            "sd": int(self._standard_definition()),
            # 'keywords': meta['keywords'],
            "internal": int(internal),
            "stream": int(stream_optimized),
            "igdb": 0,  # for games
            "imdb": 0,
            "tmdb": 0,
            "tvdb": 0,
            "mal": 0,
        }
        if personal_release is not None:
            upload_payload["personal_release"] = int(personal_release)
        if imdb_id:
            upload_payload["imdb"] = int(imdb_id.replace("t", ""))
        if tmdb_id:
            upload_payload["tmdb"] = tmdb_id
        if self.media_type is MediaType.SERIES and tvdb_id:
            upload_payload["tvdb"] = tvdb_id
        if mal_id:
            upload_payload["mal"] = mal_id

        if self.media_type is MediaType.SERIES:
            if season_number is not None:
                upload_payload["season_number"] = season_number
            # UNIT3D requires episode_number on every tv_meta category upload --
            # StoreTorrentRequest has no season-pack exemption, so omitting it
            # gets the upload rejected outright. A pack is expressed as episode
            # 0, which TorrentMeta renders as "Season Pack"; any non-zero value
            # files the torrent under Episodes as "Episode N" instead.
            if season_pack:
                upload_payload["episode_number"] = 0
            elif episode_number is not None:
                upload_payload["episode_number"] = episode_number
                if (
                    episode_number_end is not None
                    and episode_number_end != episode_number
                ):
                    upload_payload["episode_number_end"] = episode_number_end
            if season_pack:
                # not in UNIT3D's documented upload fields and unread upstream;
                # retained for forks that may consume it.
                upload_payload["season_pack"] = 1

        # some trackers have different keys for different features, we'll handle that here
        if self.tracker_name in (TrackerSelection.AITHER, TrackerSelection.REELFLIX):
            if opt_in_to_mod_queue is not None:
                upload_payload["opt_in_to_mod_queue"] = int(opt_in_to_mod_queue)
        elif self.tracker_name in (
            TrackerSelection.LST,
            TrackerSelection.SHARE_ISLAND,
            TrackerSelection.BLUTOPIA,
        ):
            if opt_in_to_mod_queue is not None:
                upload_payload["mod_queue_opt_in"] = int(opt_in_to_mod_queue)
            if draft_queue_opt_in is not None:
                upload_payload["draft_queue_opt_in"] = int(draft_queue_opt_in)

        # internal/staff only below for UNIT3D (except for HUNO)
        if featured is not None:
            upload_payload["featured"] = int(featured)
        if free is not None:
            upload_payload["free"] = int(free)
        if double_up is not None:
            upload_payload["doubleup"] = int(double_up)
        if sticky is not None:
            upload_payload["sticky"] = int(sticky)

        return upload_payload

    def _get_category_id(self) -> str:
        category_name = "TV" if self.media_type is MediaType.SERIES else "MOVIE"
        category = getattr(self.cat_enum, category_name, None)
        if not category:
            raise TrackerError(
                f"{self.tracker_name} does not support {self.media_type} uploads"
            )
        return str(self.cat_enum(category).value)

    def _get_type_id(self) -> str:
        title_lowered = release_stem(self.input_path).lower()
        title_lowered_strip_periods = title_lowered.replace(".", "")

        # remux
        if "remux" in title_lowered:
            remux_value = getattr(self.type_enum, "REMUX", None)
            if remux_value is not None:
                return str(remux_value.value)

        # disc
        if DISC_TITLE_REGEX.search(title_lowered):
            disc_value = getattr(self.type_enum, "DISC", None)
            if disc_value is not None:
                return str(disc_value.value)

        # web
        if "web" in title_lowered:
            if re.search(r"\bweb[._ -]?dl\b", title_lowered):
                webdl_value = getattr(self.type_enum, "WEBDL", None)
                if webdl_value:
                    return str(webdl_value.value)
            elif re.search(r"\bweb[._ -]?rip\b", title_lowered):
                webrip_value = getattr(self.type_enum, "WEBRIP", None)
                if webrip_value:
                    return str(webrip_value.value)
            elif re.search(
                r"\b(?:480|576|720|1080|2160|4320)[pi][._ -]?web\b"
                r"|\bweb[._ -]?(?:480|576|720|1080|2160|4320)[pi]\b"
                r"|\bweb[._ -]?(?:[xh][._ -]?26[45]|hevc|avc)\b",
                title_lowered,
            ) and not ("hdtv" in title_lowered or "hd-tv" in title_lowered):
                # bare "WEB" (no -DL/-Rip suffix) is a common scene/P2P source
                # tag for episodic web releases (e.g. "S01E01.1080p.WEB.H264").
                # Treat it the same as WEB-DL rather than falling through to
                # the codec-driven ENCODE branch below -- but only when "web"
                # sits in the release-tag region: immediately adjacent to a
                # resolution token (RES.WEB / WEB.RES) or immediately followed
                # by a codec token (WEB.CODEC). This keeps an incidental "web"
                # elsewhere in the filename -- e.g. a show title like
                # "Spider.Web.S01E01.1080p.x264-GRP" -- from being misread as
                # a source tag; that case falls through to the ENCODE branch
                # below. Also guarded against an explicit HDTV marker so a
                # real HDTV release can't be overridden.
                webdl_value = getattr(self.type_enum, "WEBDL", None)
                if webdl_value:
                    return str(webdl_value.value)

        # hdtv
        if "hdtv" in title_lowered or "hd-tv" in title_lowered:
            hdtv_value = getattr(self.type_enum, "HDTV", None)
            if hdtv_value:
                return str(hdtv_value.value)

        # encodes
        if any(
            codec in title_lowered_strip_periods
            for codec in (
                "h264",
                "x264",
                "h265",
                "x265",
            )
        ):
            encode_value = getattr(self.type_enum, "ENCODE", None)
            if encode_value:
                return str(encode_value.value)

        raise TrackerError(f"Failed to determine 'Type ID' for {self.tracker_name}")

    def _get_resolution_id(self) -> str:
        try:
            resolution = self.res_enum(
                VideoResolutionAnalyzer(self.mediainfo_obj).get_resolution()
            ).value
            return str(resolution)
        except ValueError:
            title_lowered = release_stem(self.input_path).lower()
            res_map = {
                "4320p": "RES_4320P",
                "2160p": "RES_2160P",
                "1080p": "RES_1080P",
                "1080i": "RES_1080I",
                "720p": "RES_720P",
                "576p": "RES_576P",
                "576i": "RES_576I",
                "480p": "RES_480P",
                "480i": "RES_480I",
            }
            for res, enum_name in res_map.items():
                if res in title_lowered:
                    resolution_value = getattr(self.res_enum, enum_name, None)
                    if resolution_value is not None:
                        return str(resolution_value.value)

        raise TrackerError(
            f"Failed to determine 'Resolution ID' for {self.tracker_name}"
        )

    def _standard_definition(self) -> bool:
        width = self.mediainfo_obj.video_tracks[0].width
        height = self.mediainfo_obj.video_tracks[0].height
        if width < 1280 and height < 720:
            return True
        return False

    @staticmethod
    def generate_release_title(release_title: str) -> str:
        return strip_title_dots(release_title)


class Unit3dBaseSearch:
    """
    Search Unit3d trackers utilizing their API.

    API: https://github.com/HDInnovations/UNIT3D-Community-Edition/wiki/Torrent-API-(UNIT3D-v8.3.4)
    """

    __slots__ = ("tracker_name", "search_url", "api_key", "timeout")

    def __init__(
        self,
        tracker_name: TrackerSelection,
        base_url: str,
        api_key: str,
        timeout: int = 60,
    ) -> None:
        self.tracker_name = tracker_name
        self.search_url = f"{cleanse_base_url(base_url)}/api/torrents/filter"
        self.api_key = api_key
        self.timeout = timeout

    def search(self, file_name: str) -> list[TrackerSearchResult]:
        params: dict[str, str] = {
            "api_token": self.api_key,
            "file_name": file_name,
            "perPage": "50",
        }

        results = None
        try:
            LOG.info(
                LOG.LOG_SOURCE.BE,
                f"Searching {self.tracker_name} for title: {file_name}",
            )
            with niquests.get(
                self.search_url,
                headers=TRACKER_HEADERS,
                params=params,
                timeout=self.timeout,
            ) as response:
                if response.status_code != 200:
                    raise TrackerError(
                        f"Error searching {self.tracker_name}: "
                        f"HTTP {response.status_code} ({response.reason})"
                    )
                response_json = response.json()
                results = self._convert_response(response_json)
        except niquests.exceptions.RequestException as error_message:
            raise TrackerError(str(error_message)) from error_message

        results = results if results else []
        LOG.info(
            LOG.LOG_SOURCE.BE,
            f"Total results found: {len(results)} ({self.tracker_name})",
        )
        LOG.debug(
            LOG.LOG_SOURCE.BE, f"Total results found: {results} ({self.tracker_name})"
        )
        return results

    def _convert_response(
        self, data: dict[str, Any] | None
    ) -> list[TrackerSearchResult]:
        results: list[TrackerSearchResult] = []
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


def cleanse_base_url(url: str) -> str:
    if url.endswith("/"):
        url = url[:-1]
    return url
