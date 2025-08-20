from pathlib import Path

from pymediainfo import MediaInfo

from src.backend.trackers.unit3d_base import Unit3dBaseSearch, Unit3dBaseUploader
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.uploadcx import (
    UploadCXCategory,
    UploadCXResolution,
    UploadCXType,
)
from src.payloads.media_search import MediaSearchPayload


def ulcx_uploader(
    media_type: MediaType,
    api_key: str,
    torrent_file: Path,
    file_input: Path,
    tracker_title: str | None,
    nfo: str,
    internal: bool,
    anonymous: bool,
    personal_release: bool,
    mediainfo_obj: MediaInfo,
    media_search_payload: MediaSearchPayload,
    timeout: int = 60,
) -> bool | None:
    torrent_file = Path(torrent_file)
    file_input = Path(file_input)
    uploader = UploadCXUploader(
        media_type=media_type,
        api_key=api_key,
        torrent_file=torrent_file,
        file_input=file_input,
        mediainfo_obj=mediainfo_obj,
        timeout=timeout,
    )
    upload = uploader.upload(
        tracker_title=tracker_title,
        imdb_id=media_search_payload.imdb_id,
        tmdb_id=media_search_payload.tmdb_id,
        tvdb_id=media_search_payload.tvdb_id,
        mal_id=media_search_payload.mal_id,
        nfo=nfo,
        internal=internal,
        anonymous=anonymous,
        personal_release=personal_release,
    )
    return upload


class UploadCXUploader(Unit3dBaseUploader):
    """Upload torrents to UploadCX"""

    __slots__ = ()

    def __init__(
        self,
        media_type: MediaType,
        api_key: str,
        torrent_file: Path,
        file_input: Path,
        mediainfo_obj: MediaInfo,
        timeout: int = 60,
    ) -> None:
        super().__init__(
            tracker_name=TrackerSelection.UPLOAD_CX,
            base_url="https://upload.cx",
            media_type=media_type,
            api_key=api_key,
            torrent_file=torrent_file,
            file_input=file_input,
            mediainfo_obj=mediainfo_obj,
            cat_enum=UploadCXCategory,
            res_enum=UploadCXResolution,
            type_enum=UploadCXType,
            timeout=timeout,
        )


class UploadCXSearch(Unit3dBaseSearch):
    """Search UploadCX"""

    __slots__ = ()

    def __init__(self, api_key: str, timeout: int = 60) -> None:
        super().__init__(
            tracker_name=TrackerSelection.UPLOAD_CX,
            base_url="https://upload.cx",
            api_key=api_key,
            timeout=timeout,
        )
