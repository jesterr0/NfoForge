from datetime import datetime
from pathlib import Path
import re
from typing import Type

import niquests
from pymediainfo import MediaInfo
import regex

from src.backend.trackers.utils import TRACKER_HEADERS, tracker_string_replace_map
from src.backend.utils.media_info_utils import MinimalMediaInfo
from src.backend.utils.resolution import VideoResolutionAnalyzer
from src.enums.media_mode import MediaMode
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.aither import AitherCategory, AitherResolution, AitherType
from src.enums.trackers.darkpeers import (
    DarkPeersCategory,
    DarkPeersResolution,
    DarkPeersType,
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
from src.exceptions import TrackerError
from src.logger.nfo_forge_logger import LOG
from src.payloads.tracker_search_result import TrackerSearchResult


CategoryEnums = (
    ReelFlixCategory
    | AitherCategory
    | HunoCategory
    | LSTCategory
    | DarkPeersCategory
    | ShareIslandCategory
    | UploadCXCategory
    | OnlyEncodesCategory
)
ResolutionEnums = (
    ReelFlixResolution
    | AitherResolution
    | HunoResolution
    | LSTResolution
    | DarkPeersResolution
    | ShareIslandResolution
    | UploadCXResolution
    | OnlyEncodesResolution
)
TypeEnums = (
    ReelFlixType
    | AitherType
    | HunoType
    | LSTType
    | DarkPeersType
    | ShareIslandType
    | UploadCXType
    | OnlyEncodesType
)


class Unit3dBaseUploader:
    """API: https://github.com/HDInnovations/UNIT3D/blob/master/book/src/torrent_api.md"""

    __slots__ = (
        "tracker_name",
        "upload_url",
        "base_url",
        "media_mode",
        "api_key",
        "torrent_file",
        "file_input",
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
        media_mode: MediaMode,
        api_key: str,
        torrent_file: Path,
        file_input: Path,
        mediainfo_obj: MediaInfo,
        cat_enum: Type[CategoryEnums],
        res_enum: Type[ResolutionEnums],
        type_enum: Type[TypeEnums],
        timeout: int = 60,
    ) -> None:
        self.tracker_name = tracker_name
        self.upload_url = f"{cleanse_base_url(base_url)}/api/torrents/upload"
        self.media_mode = media_mode
        self.api_key = api_key
        self.torrent_file = torrent_file
        self.file_input = file_input
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
        free: bool | None = False,
        double_up: bool | None = False,
        sticky: bool | None = False,
    ) -> bool | None:
        params = {"api_token": self.api_key}
        upload_payload = {
            "name": tracker_title
            if tracker_title
            else self.generate_release_title(self.file_input.stem),
            "description": nfo,
            "mediainfo": MinimalMediaInfo(self.file_input).get_full_mi_str(
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
        if self.media_mode is MediaMode.SERIES and tvdb_id:
            upload_payload["tvdb"] = tvdb_id
        if mal_id:
            upload_payload["mal"] = mal_id

        # some trackers have different keys for different features, we'll handle that here
        if self.tracker_name in (TrackerSelection.AITHER, TrackerSelection.REELFLIX):
            if opt_in_to_mod_queue is not None:
                upload_payload["opt_in_to_mod_queue"] = int(opt_in_to_mod_queue)
        elif self.tracker_name is TrackerSelection.LST:
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

        LOG.debug(LOG.LOG_SOURCE.BE, f"{self.tracker_name} payload: {upload_payload}")

        open_torrent = self.torrent_file.open(mode="rb")
        try:
            with niquests.post(
                url=self.upload_url,
                files={"torrent": open_torrent},
                params=params,
                data=upload_payload,
                headers=TRACKER_HEADERS,
                timeout=self.timeout,
            ) as response:
                response_json = response.json()
                # {'success': True, 'data': 'https://baseurl/torrent/download/45835.keydata', 'message': 'Torrent uploaded successfully.'}
                message = response_json.get("message")
                context = response_json.get("data")
                if response_json.get("success") is True and "successfully" in message:
                    return True
                else:
                    error_msg = f"Message='{message}' Context='{context}'"
                    raise TrackerError(error_msg)
        except (niquests.exceptions.RequestException, TrackerError) as error:
            requests_exc_error_msg = f"Failed to upload to {self.tracker_name}: {error}"
            LOG.error(LOG.LOG_SOURCE.BE, requests_exc_error_msg)
            raise TrackerError(requests_exc_error_msg)
        finally:
            open_torrent.close()

    def _get_category_id(self) -> str:
        return self.cat_enum(self.cat_enum.MOVIE).value

    def _get_type_id(self) -> str:
        title_lowered = str(self.file_input.stem).lower()
        title_lowered_strip_periods = title_lowered.replace(".", "")

        # remux
        if "remux" in title_lowered:
            return self.type_enum.REMUX.value

        # disc
        if regex.search(
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
            return self.type_enum.DISC.value

        # web
        if "web" in title_lowered:
            if re.match(r"web.?dl", title_lowered):
                webdl_value = getattr(self.type_enum, "WEBDL", None)
                if webdl_value:
                    return webdl_value.value
            elif re.match(r"web.?rip", title_lowered):
                webrip_value = getattr(self.type_enum, "WEBRIP", None)
                if webrip_value:
                    return webrip_value.value

        # hdtv
        if "hdtv" in title_lowered or "hd-tv" in title_lowered:
            hdtv_value = getattr(self.type_enum, "HDTV", None)
            if hdtv_value:
                return hdtv_value.value

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
                return encode_value.value

        raise TrackerError(f"Failed to determine 'Type ID' for {self.tracker_name}")

    def _get_resolution_id(self) -> str:
        try:
            resolution = self.res_enum(
                VideoResolutionAnalyzer(self.mediainfo_obj).get_resolution()
            ).value
            return resolution
        except ValueError:
            title_lowered = self.file_input.stem.lower()
            res_map = {
                "4320p": self.res_enum.RES_4320P,
                "2160p": self.res_enum.RES_2160P,
                "1080p": self.res_enum.RES_1080P,
                "1080i": self.res_enum.RES_1080I,
                "720p": self.res_enum.RES_720P,
                "576p": self.res_enum.RES_576P,
                "576i": self.res_enum.RES_576I,
                "480p": self.res_enum.RES_480P,
                "480i": self.res_enum.RES_480I,
            }
            for res, enum in res_map.items():
                if res in title_lowered:
                    return enum.value

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
        name = release_title.replace(".", " ")
        name = re.sub(r"\s{2,}", " ", name)
        for replace_key, replace_val in tracker_string_replace_map().items():
            name = name.replace(replace_key, replace_val)
        return name


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
        params = {
            "api_token": self.api_key,
            "file_name": file_name,
            "perPage": 50,
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
                if response.ok and response.status_code == 200:
                    response_json = response.json()
                    results = self._convert_response(response_json)
        except niquests.exceptions.RequestException as error_message:
            raise TrackerError(error_message)

        results = results if results else []
        LOG.info(
            LOG.LOG_SOURCE.BE,
            f"Total results found: {len(results)} ({self.tracker_name})",
        )
        LOG.debug(
            LOG.LOG_SOURCE.BE, f"Total results found: {results} ({self.tracker_name})"
        )
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


def cleanse_base_url(url: str) -> str:
    if url.endswith("/"):
        url = url[:-1]
    return url
