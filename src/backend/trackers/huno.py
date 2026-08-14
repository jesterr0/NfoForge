from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urljoin

import niquests
from niquests.typing import MultiPartFilesAltType
from pymediainfo import MediaInfo

from src.backend.trackers.unit3d_base import Unit3dBaseSearch, Unit3dBaseUploader
from src.backend.trackers.utils import TRACKER_HEADERS
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.huno import HunoCategory, HunoResolution, HunoType
from src.exceptions import TrackerError
from src.payloads.media_search import MediaSearchPayload


def huno_uploader(
    media_type: MediaType,
    api_key: str,
    torrent_file: Path,
    input_path: Path,
    nfo: str,
    internal: bool,
    anonymous: bool,
    mediainfo_obj: MediaInfo,
    media_search_payload: MediaSearchPayload,
    timeout: int = 60,
    season_number: int | None = None,
    episode_number: int | None = None,
    episode_number_end: int | None = None,
    season_pack: bool = False,
) -> bool | None:
    uploader = HunoUploader(
        media_type=media_type,
        api_key=api_key,
        torrent_file=torrent_file,
        input_path=input_path,
        mediainfo_obj=mediainfo_obj,
        timeout=timeout,
    )
    upload = uploader.upload(
        tracker_title=None,
        imdb_id=media_search_payload.imdb_id,
        tmdb_id=media_search_payload.tmdb_id,
        tvdb_id=media_search_payload.tvdb_id,
        mal_id=media_search_payload.mal_id,
        nfo=nfo,
        internal=internal,
        anonymous=anonymous,
        personal_release=None,
        opt_in_to_mod_queue=None,
        featured=None,
        free=None,
        double_up=None,
        sticky=None,
        season_number=season_number,
        episode_number=episode_number,
        episode_number_end=episode_number_end,
        season_pack=season_pack,
    )
    return upload


class HunoUploader(Unit3dBaseUploader):
    """Upload torrents to HUNO"""

    __slots__ = ()

    _AUTO_MODE_FIELDS = frozenset(
        {
            "category_id",
            "type_id",
            "tmdb",
            "imdb",
            "tvdb",
            "mal",
            "season_number",
            "episode_number",
            "episode_number_end",
            "season_pack",
            "anonymous",
            "internal",
        }
    )

    def __init__(
        self,
        media_type: MediaType,
        api_key: str,
        torrent_file: Path,
        input_path: Path,
        mediainfo_obj: MediaInfo,
        timeout: int = 60,
    ) -> None:
        super().__init__(
            tracker_name=TrackerSelection.HUNO,
            base_url=TrackerSelection.HUNO.get_root_url(),
            media_type=media_type,
            api_key=api_key,
            torrent_file=torrent_file,
            input_path=input_path,
            mediainfo_obj=mediainfo_obj,
            cat_enum=HunoCategory,
            res_enum=HunoResolution,
            type_enum=HunoType,
            timeout=timeout,
        )

    def _prepare_upload_request(
        self, upload_payload: dict[str, Any], open_torrent: BinaryIO
    ) -> tuple[dict[str, Any], MultiPartFilesAltType]:
        """Build HUNO's auto-mode multipart request.

        HUNO requires the description and MediaInfo to be actual ``.txt``
        uploads. It generates the release name and technical attributes from
        the torrent filename and MediaInfo, so legacy UNIT3D fields are not
        forwarded as accidental overrides.
        """
        payload = upload_payload.copy()
        description = payload.pop("description", "")
        mediainfo = payload.pop("mediainfo", "")

        if payload.get("season_pack") == 1:
            # HUNO distinguishes a pack by season_pack=1 and requires the
            # episode field to be absent. Episode zero means a pilot there.
            payload.pop("episode_number", None)
            payload.pop("episode_number_end", None)

        data = {
            key: value
            for key, value in payload.items()
            if key in self._AUTO_MODE_FIELDS
        }
        files: MultiPartFilesAltType = {
            "torrent": open_torrent,
            "description": (
                "description.txt",
                str(description or "").encode("utf-8"),
                "text/plain",
            ),
            "mediainfo": (
                "mediainfo.txt",
                str(mediainfo or "").encode("utf-8"),
                "text/plain",
            ),
        }
        return data, files

    @staticmethod
    def _torrent_resource(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None

        resource: Any = payload.get("torrent")
        if not isinstance(resource, dict):
            resource = payload.get("data")
        if isinstance(resource, dict) and isinstance(resource.get("torrent"), dict):
            resource = resource["torrent"]
        return resource if isinstance(resource, dict) else None

    @classmethod
    def _download_link(cls, payload: Any) -> str | None:
        resource = cls._torrent_resource(payload)
        if resource is None:
            return None
        attributes = resource.get("attributes")
        for values in (attributes, resource):
            if isinstance(values, dict):
                download_link = values.get("download_link")
                if isinstance(download_link, str) and download_link:
                    return download_link
        return None

    @classmethod
    def _torrent_id(cls, payload: Any) -> str | None:
        resource = cls._torrent_resource(payload)
        if resource is None:
            return None
        attributes = resource.get("attributes")
        for values in (resource, attributes):
            if isinstance(values, dict):
                torrent_id = values.get("id")
                if isinstance(torrent_id, (str, int)) and str(torrent_id):
                    return str(torrent_id)
        return None

    def _resolve_uploaded_torrent_download_url(self, context: Any) -> str:
        # Accept HUNO's former UNIT3D response during a rolling server upgrade.
        if not isinstance(context, dict):
            return super()._resolve_uploaded_torrent_download_url(context)

        download_link = self._download_link(context)
        if download_link:
            return urljoin(f"{self.base_url}/", download_link)

        torrent_id = self._torrent_id(context)
        if torrent_id is None:
            raise TrackerError(
                "HUNO accepted the upload but did not return a torrent ID or "
                "download link",
                retryable=False,
                server_accepted=True,
                phase="download",
            )

        details_url = f"{self.base_url.rstrip('/')}/api/torrents/{torrent_id}"
        try:
            with niquests.get(
                details_url,
                params={"api_token": self.api_key},
                headers=TRACKER_HEADERS,
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()
                details = response.json()
        except niquests.exceptions.RequestException as error:
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            retryable = not isinstance(status_code, int) or (
                status_code == 408 or status_code == 429 or status_code >= 500
            )
            raise TrackerError(
                f"Failed to fetch HUNO torrent details: {error}",
                retryable=retryable,
                server_accepted=True,
                phase="download",
                status_code=status_code if isinstance(status_code, int) else None,
            ) from error

        download_link = self._download_link(details)
        if download_link:
            return urljoin(f"{self.base_url}/", download_link)
        raise TrackerError(
            "HUNO torrent details did not include a download link",
            retryable=True,
            server_accepted=True,
            phase="download",
        )


class HunoSearch(Unit3dBaseSearch):
    """Search HUNO"""

    __slots__ = ()

    def __init__(self, api_key: str, timeout: int = 60) -> None:
        super().__init__(
            tracker_name=TrackerSelection.HUNO,
            base_url=TrackerSelection.HUNO.get_root_url(),
            api_key=api_key,
            timeout=timeout,
        )
