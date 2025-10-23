from pathlib import Path

from pymediainfo import MediaInfo

from src.backend.trackers.unit3d_base import Unit3dBaseSearch, Unit3dBaseUploader
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.darkpeers import (
    DarkPeersCategory,
    DarkPeersResolution,
    DarkPeersType,
)
from src.payloads.media_search import MediaSearchPayload


def dp_uploader(
    media_type: MediaType,
    api_key: str,
    torrent_file: Path,
    input_path: Path,
    tracker_title: str | None,
    nfo: str,
    internal: bool,
    anonymous: bool,
    mediainfo_obj: MediaInfo,
    media_search_payload: MediaSearchPayload,
    timeout: int = 60,
) -> bool | None:
    uploader = DarkPeersUploader(
        media_type=media_type,
        api_key=api_key,
        torrent_file=torrent_file,
        input_path=input_path,
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
    )
    return upload


class DarkPeersUploader(Unit3dBaseUploader):
    """Upload torrents to DarkPeers"""

    __slots__ = ()

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
            tracker_name=TrackerSelection.DARK_PEERS,
            base_url="https://darkpeers.org",
            media_type=media_type,
            api_key=api_key,
            torrent_file=torrent_file,
            input_path=input_path,
            mediainfo_obj=mediainfo_obj,
            cat_enum=DarkPeersCategory,
            res_enum=DarkPeersResolution,
            type_enum=DarkPeersType,
            timeout=timeout,
        )


class DarkPeersSearch(Unit3dBaseSearch):
    """Search DarkPeers"""

    __slots__ = ()

    def __init__(self, api_key: str, timeout: int = 60) -> None:
        super().__init__(
            tracker_name=TrackerSelection.DARK_PEERS,
            base_url="https://darkpeers.org",
            api_key=api_key,
            timeout=timeout,
        )
