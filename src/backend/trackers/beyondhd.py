from datetime import datetime
from os import PathLike
from pathlib import Path
import re

import niquests
import regex

from src.backend.trackers.utils import TRACKER_HEADERS
from src.backend.utils.media_info_utils import MinimalMediaInfo
from src.enums.media_mode import MediaMode
from src.enums.trackers.beyondhd import (
    BHDCategoryID,
    BHDLiveRelease,
    BHDPromo,
    BHDSource,
    BHDType,
)
from src.exceptions import TrackerError
from src.logger.nfo_forge_logger import LOG
from src.payloads.tracker_search_result import TrackerSearchResult


def bhd_uploader(
    api_key: str,
    torrent_file: PathLike[str] | Path,
    file_input: PathLike[str] | Path,
    tracker_title: str | None,
    media_mode: MediaMode,
    imdb_id: str | None,
    tmdb_id: str | None,
    nfo: str,
    internal: bool,
    live_release: BHDLiveRelease,
    anonymous: bool,
    promo: BHDPromo,
    timeout: int,
) -> str | None:
    uploader = BHDUploader(
        api_key=api_key,
        torrent_file=torrent_file,
        file_input=file_input,
        media_mode=media_mode,
        timeout=timeout,
    )
    return uploader.upload(
        tracker_title=tracker_title,
        imdb_id=imdb_id,
        tmdb_id=tmdb_id,
        nfo=nfo,
        internal=internal,
        live_release=live_release,
        anonymous=anonymous,
        promo=promo,
    )


class BHDUploader:
    """BeyondHD Uploader utilizing their API"""

    def __init__(
        self,
        api_key: str,
        torrent_file: PathLike[str] | Path,
        file_input: PathLike[str] | Path,
        media_mode: MediaMode,
        timeout: int = 60,
    ) -> None:
        self._upload_url = f"https://beyond-hd.me/api/upload/{api_key}"
        self.torrent_file = Path(torrent_file)
        self.file_input = Path(file_input)
        self.media_mode = media_mode
        self.timeout = timeout

    def upload(
        self,
        tracker_title: str | None,
        imdb_id: str | None = None,
        tmdb_id: str | None = None,
        nfo: str | None = None,
        internal: bool = False,
        live_release: BHDLiveRelease = BHDLiveRelease.LIVE,
        anonymous: bool = False,
        promo: BHDPromo | None = None,
    ) -> str | None:
        upload_payload = {
            "name": tracker_title
            if tracker_title
            else self.generate_release_title(self.file_input.stem),
            "category_id": self._category_id(),
            "type": self._type(),
            "source": self._source(),
            "internal": int(internal),
            "live": live_release.value,
            "anon": int(anonymous),
            # "stream": 1,
        }
        if imdb_id:
            upload_payload["imdb_id"] = imdb_id
        if tmdb_id:
            upload_payload["tmdb_id"] = tmdb_id
        if nfo:
            upload_payload["description"] = nfo
            upload_payload["nfo"] = nfo
        if promo:
            upload_payload["promo"] = promo.value

        LOG.debug(
            LOG.LOG_SOURCE.BE,
            f"BeyondHD payload: {upload_payload}",
        )

        try:
            response = niquests.post(
                self._upload_url,
                data=upload_payload,
                files=self._files(),
                timeout=self.timeout,
            )
            if not response.ok or response.status_code != 200:
                response_error_msg = f"Failed to upload torrent. Reason: {response.reason}, Status Code: {response.status_code}"
                LOG.error(LOG.LOG_SOURCE.BE, response_error_msg)
                raise TrackerError(response_error_msg)

            response_json = response.json()
            if response_json.get("success"):
                status_code = response_json.get("status_code")
                if status_code == 0:
                    status_0_error_msg = f"Failed to upload torrent: {response_json.get('status_message')}"
                    LOG.error(LOG.LOG_SOURCE.BE, status_0_error_msg)
                    raise TrackerError(status_0_error_msg)
                elif status_code == 1:
                    status_1_msg = "Successfully uploaded as a draft"
                    LOG.info(LOG.LOG_SOURCE.BE, status_1_msg)
                    return status_1_msg
                elif status_code == 2:
                    status_2_msg = f"Successfully uploaded (live): {response_json.get('status_message')}"
                    LOG.info(LOG.LOG_SOURCE.BE, status_2_msg)
                    return status_2_msg
            else:
                failed_error_msg = (
                    f"Failed to upload torrent: {response_json.get('status_message')}"
                )
                LOG.error(LOG.LOG_SOURCE.BE, failed_error_msg)
                raise TrackerError(failed_error_msg)

        except niquests.exceptions.RequestException as error:
            requests_exc_error_msg = f"Failed to upload to BeyondHD: {error}"
            LOG.error(LOG.LOG_SOURCE.BE, requests_exc_error_msg)
            raise TrackerError(requests_exc_error_msg)

    def _category_id(self) -> int | None:
        if self.media_mode == MediaMode.MOVIES:
            return BHDCategoryID.MOVIE.value
        elif self.media_mode == MediaMode.SERIES:
            return BHDCategoryID.TV.value

    def _type(self) -> str:
        title_lowered = str(self.file_input.stem).lower()
        title_lowered_strip_periods = title_lowered.replace(".", "")

        # remux
        if "remux" in title_lowered:
            if "dvd" in title_lowered:
                return BHDType.DVD_REMUX.value
            elif "1080i" in title_lowered or "1080p" in title_lowered:
                return BHDType.BD_REMUX.value
            elif "2160p" in title_lowered or "uhd" in title_lowered:
                return BHDType.UHD_REMUX.value

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
            input_file_size = self.file_input.stat().st_size
            if input_file_size <= 26_843_545_600:
                return BHDType.BD_25.value
            elif input_file_size <= 53_687_091_200:
                if "1080i" in title_lowered or "1080p" in title_lowered:
                    return BHDType.BD_50.value
                elif "2160p" in title_lowered:
                    return BHDType.UHD_50.value
            elif input_file_size <= 70_866_960_384:
                return BHDType.UHD_66.value
            elif input_file_size <= 107_374_182_400:
                return BHDType.UHD_100.value

        # dvd5/dvd9
        elif "dvd5" in title_lowered_strip_periods:
            return BHDType.DVD_5.value
        elif "dvd9" in title_lowered_strip_periods:
            return BHDType.DVD_9.value

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
            if "480p" in title_lowered:
                return BHDType.P_480P.value
            elif "540p" in title_lowered:
                return BHDType.P_540P.value
            elif "576p" in title_lowered:
                return BHDType.P_576P.value
            elif "720p" in title_lowered:
                return BHDType.P_720P.value
            elif "1080i" in title_lowered:
                return BHDType.P_1080I.value
            elif "1080p" in title_lowered:
                return BHDType.P_1080P.value
            elif "2160p" in title_lowered:
                return BHDType.P_2160P.value

        return BHDType.OTHER.value

    def _source(self) -> str:
        title_lowered = str(self.file_input.stem).lower()
        title_lowered = re.sub(r"\W", ".", title_lowered)
        title_lowered = re.sub(r"\.{2,}", ".", title_lowered)
        if "bluray" in title_lowered:
            return BHDSource.BLURAY.value
        elif "hddvd" in title_lowered:
            return BHDSource.HD_DVD.value
        elif "dvd" in title_lowered:
            return BHDSource.DVD.value
        elif "hdtv" in title_lowered:
            return BHDSource.HDTV.value
        elif "web" in title_lowered:
            return BHDSource.WEB.value
        else:
            raise TrackerError(
                f"Input file name must contain one of {', '.join([x.value for x in BHDSource])} "
                "to upload to BeyondHD"
            )

    def _files(self) -> dict:
        with open(self.torrent_file, "rb") as torrent_file:
            return {
                "file": torrent_file.read(),
                "mediainfo": self._cleaned_media_info(),
            }

    def _cleaned_media_info(self) -> str:
        return MinimalMediaInfo(self.file_input).get_full_mi_str(cleansed=True)

    @staticmethod
    def generate_release_title(release_title: str) -> str:
        name = release_title.replace(".", " ")
        name = re.sub(r"\s{2,}", " ", name)
        return name


class BHDSearch:
    """Search BeyondHD utilizing their API"""

    def __init__(
        self, api_key: str, rss_key: str | None = None, timeout: int = 60
    ) -> None:
        self._search_url = f"https://beyond-hd.me/api/torrents/{api_key}"
        self._rss_key = rss_key
        self._timeout = timeout

    def search(self, title: Path) -> list[TrackerSearchResult]:
        payload = {"action": "search", "file_name": title.name}
        if self._rss_key:
            payload["rsskey"] = self._rss_key

        results = []
        try:
            LOG.info(LOG.LOG_SOURCE.BE, f"Searching BeyondHD for title: {title}")
            response = niquests.post(
                url=self._search_url,
                params=payload,
                headers=TRACKER_HEADERS,
                timeout=self._timeout,
            )
            response_json = response.json()
            self._check_response(response_json)
            results = self._convert_response(response_json.get("results", []))
            LOG.info(LOG.LOG_SOURCE.BE, f"Total results found: {len(results)}")
            LOG.debug(LOG.LOG_SOURCE.BE, f"Total results found: {results}")
        except niquests.exceptions.RequestException as error_message:
            raise TrackerError(error_message)

        return results

    def _convert_response(self, data: list[dict]) -> list[TrackerSearchResult]:
        results = []

        for release in data:
            result = TrackerSearchResult(
                name=release.get("name"),
                url=release.get("url"),
                download_link=release.get("download_url"),
                release_type=release.get("type"),
                created_at=self._handle_date(release.get("created_at")),
                seeders=release.get("seeders"),
                leechers=release.get("leechers"),
                grabs=release.get("times_completed"),
                imdb_id=release.get("imdb_id"),
                tmdb_id=self._tmdb_id_format(release.get("tmdb_id", "")),
                uploader=release.get("uploaded_by"),
                info_hash=release.get("info_hash"),
            )
            results.append(result)

        return results

    @staticmethod
    def _check_response(response_json: dict) -> None:
        try:
            if not response_json["status_code"]:
                if "invalid api key" in str(response_json["status_message"]).lower():
                    raise TrackerError("Invalid API Key")
                else:
                    raise TrackerError(response_json["status_message"])
        except Exception as error:
            raise TrackerError(error)

    @staticmethod
    def _handle_date(timestamp: str | None) -> datetime | None:
        if timestamp:
            return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        return timestamp if timestamp else None

    @staticmethod
    def _tmdb_id_format(id_str: str | None) -> str | None:
        if id_str:
            id_str = id_str.replace("movie/", "")
        return id_str
