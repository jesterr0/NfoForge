from pathlib import Path

from pymediainfo import MediaInfo
from typing_extensions import override

from src.backend.trackers.unit3d_base import Unit3dBaseSearch, Unit3dBaseUploader
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.lst import LSTCategory, LSTResolution, LSTType
from src.exceptions import TrackerError
from src.payloads.media_search import MediaSearchPayload


def lst_uploader(
    media_type: MediaType,
    api_key: str,
    torrent_file: Path,
    input_path: Path,
    tracker_title: str | None,
    nfo: str,
    internal: bool,
    anonymous: bool,
    personal_release: bool,
    opt_in_to_mod_queue: bool,
    draft_queue_opt_in: bool,
    featured: bool,
    free: bool,
    double_up: bool,
    sticky: bool,
    mediainfo_obj: MediaInfo,
    media_search_payload: MediaSearchPayload,
    timeout: int = 60,
    season_number: int | None = None,
    episode_number: int | None = None,
    season_pack: bool = False,
) -> bool | None:
    uploader = LSTUploader(
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
        opt_in_to_mod_queue=opt_in_to_mod_queue,
        draft_queue_opt_in=draft_queue_opt_in,
        featured=featured,
        free=free,
        double_up=double_up,
        sticky=sticky,
        season_number=season_number,
        episode_number=episode_number,
        season_pack=season_pack,
    )
    return upload


class LSTUploader(Unit3dBaseUploader):
    """Upload torrents to LST"""

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
            tracker_name=TrackerSelection.LST,
            base_url=TrackerSelection.LST.get_root_url(),
            media_type=media_type,
            api_key=api_key,
            torrent_file=torrent_file,
            input_path=input_path,
            mediainfo_obj=mediainfo_obj,
            cat_enum=LSTCategory,
            res_enum=LSTResolution,
            type_enum=LSTType,
            timeout=timeout,
        )

    @override
    def _get_resolution_id(self) -> str:
        try:
            return super()._get_resolution_id()
        except TrackerError:
            return LSTResolution.RES_OTHER.value


class LSTSearch(Unit3dBaseSearch):
    """Search LST"""

    __slots__ = ()

    def __init__(self, api_key: str, timeout: int = 60) -> None:
        super().__init__(
            tracker_name=TrackerSelection.LST,
            base_url=TrackerSelection.LST.get_root_url(),
            api_key=api_key,
            timeout=timeout,
        )
