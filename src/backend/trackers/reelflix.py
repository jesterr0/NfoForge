import re
import regex
import requests
from datetime import datetime

from pathlib import Path
from pymediainfo import MediaInfo

from src.logger.nfo_forge_logger import LOG
from src.enums.trackers.reelflix import (
    ReelFlixCategory,
    ReelFlixResolution,
    ReelFlixType,
)
from src.exceptions import TrackerError
from src.backend.utils.resolution import VideoResolutionAnalyzer
from src.backend.trackers.utils import TRACKER_HEADERS

from src.backend.utils.media_info_utils import MinimalMediaInfo
from src.payloads.tracker_search_result import TrackerSearchResult
from src.payloads.media_search import MediaSearchPayload


def rf_uploader(
    api_key: str,
    torrent_file: Path,
    file_input: Path,
    nfo: str,
    internal: bool,
    anonymous: bool,
    personal_release: bool,
    stream_optimized: bool,
    opt_in_to_mod_queue: bool,
    featured: bool,
    free: bool,
    double_up: bool,
    sticky: bool,
    mediainfo_obj: MediaInfo,
    media_search_payload: MediaSearchPayload,
    timeout: int = 60,
) -> bool | None:
    torrent_file = Path(torrent_file)
    file_input = Path(file_input)
    uploader = ReelFlixUploader(
        api_key=api_key,
        torrent_file=torrent_file,
        file_input=file_input,
        mediainfo_obj=mediainfo_obj,
        timeout=timeout,
    )
    upload = uploader.upload(
        imdb_id=media_search_payload.imdb_id,
        tmdb_id=media_search_payload.tmdb_id,
        tvdb_id=media_search_payload.tvdb_id,
        mal_id=media_search_payload.mal_id,
        nfo=nfo,
        internal=internal,
        anonymous=anonymous,
        personal_release=personal_release,
        stream_optimized=stream_optimized,
        opt_in_to_mod_queue=opt_in_to_mod_queue,
        featured=featured,
        free=free,
        double_up=double_up,
        sticky=sticky,
    )
    return upload


class ReelFlixUploader:
    """
    Upload torrents to ReelFliX

    API: https://github.com/HDInnovations/UNIT3D-Community-Edition/wiki/Torrent-API-(UNIT3D-v8.3.4)
    """

    UPLOAD_URL = "https://reelflix.xyz/api/torrents/upload"

    # TODO: when adding DISC support we'll need to add region_ids and distributor_ids

    def __init__(
        self,
        api_key: str,
        torrent_file: Path,
        file_input: Path,
        mediainfo_obj: MediaInfo,
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key
        self.torrent_file = torrent_file
        self.file_input = file_input
        self.mediainfo_obj = mediainfo_obj
        self.timeout = timeout

    def upload(
        self,
        imdb_id: str | None = None,
        tmdb_id: str | None = None,
        tvdb_id: str | None = None,
        mal_id: str | None = None,
        nfo: str | None = None,
        internal: bool = False,
        anonymous: bool = False,
        personal_release: bool = True,
        stream_optimized: bool = False,
        opt_in_to_mod_queue: bool = False,
        featured: bool = False,
        free: bool = False,
        double_up: bool = False,
        sticky: bool = False,
    ) -> bool | None:
        params = {"api_token": self.api_key}
        upload_payload = {
            "name": self._generate_name(),
            "description": nfo,
            "mediainfo": MinimalMediaInfo(self.file_input).get_full_mi_str(
                cleansed=True
            ),
            # 'bdinfo': bd_dump,
            "category_id": self._get_category_id(ReelFlixCategory.MOVIE),
            "type_id": self._get_type_id(),
            "resolution_id": self._get_resolution_id(),
            "anonymous": int(anonymous),
            "sd": int(self._standard_definition()),
            # 'keywords': meta['keywords'],
            "internal": int(internal),
            "personal_release": int(personal_release),
            "stream": int(stream_optimized),
            "opt_in_to_mod_queue": int(opt_in_to_mod_queue),
            "igdb": 0,
            "mal": 0,
            # internal/staff only below
            "featured": int(featured),
            "free": int(free),
            "doubleup": int(double_up),
            "sticky": int(sticky),
        }
        if imdb_id:
            upload_payload["imdb"] = imdb_id.replace("t", "")
        if tmdb_id:
            upload_payload["tmdb"] = tmdb_id
        if tvdb_id:
            upload_payload["tvdb"] = tvdb_id
        if mal_id:
            upload_payload["mal"] = mal_id

        LOG.debug(LOG.LOG_SOURCE.BE, f"ReelFliX payload: {upload_payload}")

        open_torrent = self.torrent_file.open(mode="rb")
        try:
            with requests.post(
                url=self.UPLOAD_URL,
                files={"torrent": open_torrent},
                params=params,
                data=upload_payload,
                headers=TRACKER_HEADERS,
                timeout=self.timeout,
            ) as response:
                response_json = response.json()
                # {'success': True, 'data': 'https://reelflix.xyz/torrent/download/45835.keydata', 'message': 'Torrent uploaded successfully.'}
                message = response_json.get("message")
                context = response_json.get("data")
                if response_json.get("success") is True and "successfully" in message:
                    return True
                else:
                    error_msg = f"Message='{message}' Context='{context}'"
                    raise TrackerError(error_msg)
        except (requests.exceptions.RequestException, TrackerError) as error:
            requests_exc_error_msg = f"Failed to upload to ReelFliX: {error}"
            LOG.error(LOG.LOG_SOURCE.BE, requests_exc_error_msg)
            raise TrackerError(requests_exc_error_msg)
        finally:
            open_torrent.close()

    def _generate_name(self) -> str:
        name = str(self.file_input.stem).replace(".", " ")
        name = re.sub(r"\s{2,}", " ", name)
        return name

    def _get_category_id(self, cat: ReelFlixCategory) -> str:
        return ReelFlixCategory(cat).value

    def _get_type_id(self) -> str:
        title_lowered = str(self.file_input.stem).lower()
        title_lowered_strip_periods = title_lowered.replace(".", "")

        # remux
        if "remux" in title_lowered:
            return ReelFlixType.REMUX.value

        # disc
        elif regex.search(
            (
                r"^(?!.*\b((?<!HD[._ -]|HD)DVD|BDRip|720p|MKV|XviD"
                r"|WMV|d3g|(BD)?REMUX|^(?=.*1080p)(?=.*HEVC)|[xh][-_. ]"
                r"?26[45]|German.*[DM]L|((?<=\d{4}).*German.*([DM]L)?)"
                r"(?=.*\b(AVC|HEVC|VC[-_. ]?1|MVC|MPEG[-_. ]?2)\b))\b)(((?=.*\b(Blu[-_. ]?ray"
                r"|BD|HD[-_. ]?DVD)\b)(?=.*\b(AVC|HEVC|VC[-_. ]?1|MVC|"
                r"MPEG[-_. ]?2|BDMV|ISO)\b))|^((?=.*\b(((?=.*\b((.*_)?COMPLETE.*"
                r"|Dis[ck])\b)(?=.*(Blu[-_. ]?ray|HD[-_. ]?DVD)))|3D[-_. ]?BD|"
                r"BR[-_. ]?DISK|Full[-_. ]?Blu[-_. ]?ray|^((?=.*((BD|UHD)[-_. ]?(25"
                r"|50|66|100|ISO)))))))).*"
            ),
            title_lowered,
        ):
            return ReelFlixType.DISC.value

        # web
        elif "web" in title_lowered:
            if re.match(r"web.?dl", title_lowered):
                return ReelFlixType.WEBDL.value
            elif re.match(r"web.?rip", title_lowered):
                return ReelFlixType.WEBRIP.value

        # hdtv
        elif "hdtv" in title_lowered or "hd-tv" in title_lowered:
            return ReelFlixType.HDTV.value

        # encodes
        elif any(
            codec in title_lowered_strip_periods
            for codec in (
                "h264",
                "x264",
                "h265",
                "x265",
            )
        ):
            return ReelFlixType.ENCODE.value

        raise TrackerError("Failed to determine 'Type ID' for ReelFliX")

    def _get_resolution_id(self) -> str:
        try:
            resolution = ReelFlixResolution(
                VideoResolutionAnalyzer(self.mediainfo_obj).get_resolution()
            ).value
            return resolution
        except ValueError:
            title_lowered = self.file_input.stem.lower()
            res_map = {
                "4320p": ReelFlixResolution.RES_4320P,
                "2160p": ReelFlixResolution.RES_2160P,
                "1080p": ReelFlixResolution.RES_1080P,
                "1080i": ReelFlixResolution.RES_1080I,
                "720p": ReelFlixResolution.RES_720P,
                "576p": ReelFlixResolution.RES_576P,
                "576i": ReelFlixResolution.RES_576I,
                "480p": ReelFlixResolution.RES_480P,
                "480i": ReelFlixResolution.RES_480I,
            }
            for res, enum in res_map.items():
                if res in title_lowered:
                    return enum.value

        raise TrackerError("Failed to determine 'Resolution ID' for ReelFliX")

    def _standard_definition(self) -> bool:
        width = self.mediainfo_obj.video_tracks[0].width
        height = self.mediainfo_obj.video_tracks[0].height
        if width < 1280 and height < 720:
            return True
        return False


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
