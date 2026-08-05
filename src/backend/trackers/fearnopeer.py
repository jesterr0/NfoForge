from pathlib import Path

from pymediainfo import MediaInfo

from src.backend.trackers.unit3d_base import Unit3dBaseSearch, Unit3dBaseUploader
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.fearnopeer import (
    FearNoPeerCategory,
    FearNoPeerResolution,
    FearNoPeerType,
)
from src.payloads.media_search import MediaSearchPayload


def fnp_uploader(
    media_type: MediaType,
    api_key: str,
    torrent_file: Path,
    input_path: Path,
    tracker_title: str | None,
    nfo: str,
    internal: bool,
    anonymous: bool,
    personal_release: bool,
    mediainfo_obj: MediaInfo,
    media_search_payload: MediaSearchPayload,
    timeout: int = 60,
    season_number: int | None = None,
    episode_number: int | None = None,
    season_pack: bool = False,
) -> bool | None:
    uploader = FearNoPeerUploader(
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
        personal_release=personal_release,
        season_number=season_number,
        episode_number=episode_number,
        season_pack=season_pack,
    )
    return upload


class FearNoPeerUploader(Unit3dBaseUploader):
    """Upload torrents to FearNoPeer"""

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
            tracker_name=TrackerSelection.FEAR_NO_PEER,
            base_url=TrackerSelection.FEAR_NO_PEER.get_root_url(),
            media_type=media_type,
            api_key=api_key,
            torrent_file=torrent_file,
            input_path=input_path,
            mediainfo_obj=mediainfo_obj,
            cat_enum=FearNoPeerCategory,
            res_enum=FearNoPeerResolution,
            type_enum=FearNoPeerType,
            timeout=timeout,
        )


class FearNoPeerSearch(Unit3dBaseSearch):
    """Search FearNoPeer"""

    __slots__ = ()

    def __init__(self, api_key: str, timeout: int = 60) -> None:
        super().__init__(
            tracker_name=TrackerSelection.FEAR_NO_PEER,
            base_url=TrackerSelection.FEAR_NO_PEER.get_root_url(),
            api_key=api_key,
            timeout=timeout,
        )
