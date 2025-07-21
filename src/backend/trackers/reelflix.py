from pathlib import Path

from pymediainfo import MediaInfo

from src.backend.trackers.unit3d_base import Unit3dBaseSearch, Unit3dBaseUploader
from src.enums.media_mode import MediaMode
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.reelflix import (
    ReelFlixCategory,
    ReelFlixResolution,
    ReelFlixType,
)
from src.payloads.media_search import MediaSearchPayload


def rf_uploader(
    media_mode: MediaMode,
    api_key: str,
    torrent_file: Path,
    file_input: Path,
    tracker_title: str | None,
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
        media_mode=media_mode,
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
        stream_optimized=stream_optimized,
        opt_in_to_mod_queue=opt_in_to_mod_queue,
        featured=featured,
        free=free,
        double_up=double_up,
        sticky=sticky,
    )
    return upload


class ReelFlixUploader(Unit3dBaseUploader):
    """Upload torrents to ReelFliX"""

    __slots__ = ()

    def __init__(
        self,
        media_mode: MediaMode,
        api_key: str,
        torrent_file: Path,
        file_input: Path,
        mediainfo_obj: MediaInfo,
        timeout: int = 60,
    ) -> None:
        super().__init__(
            tracker_name=TrackerSelection.REELFLIX,
            base_url="https://reelflix.xyz",
            media_mode=media_mode,
            api_key=api_key,
            torrent_file=torrent_file,
            file_input=file_input,
            mediainfo_obj=mediainfo_obj,
            cat_enum=ReelFlixCategory,
            res_enum=ReelFlixResolution,
            type_enum=ReelFlixType,
            timeout=timeout,
        )


class ReelFlixSearch(Unit3dBaseSearch):
    """Search ReelFliX"""

    __slots__ = ()

    def __init__(self, api_key: str, timeout: int = 60) -> None:
        super().__init__(
            tracker_name=TrackerSelection.REELFLIX,
            base_url="https://reelflix.xyz",
            api_key=api_key,
            timeout=timeout,
        )
