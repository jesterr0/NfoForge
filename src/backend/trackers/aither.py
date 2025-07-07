from pathlib import Path

from pymediainfo import MediaInfo

from src.backend.trackers import Unit3dBaseSearch, Unit3dBaseUploader
from src.enums.media_mode import MediaMode
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.aither import AitherCategory, AitherResolution, AitherType
from src.exceptions import TrackerError
from src.payloads.media_search import MediaSearchPayload


def aither_uploader(
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
    uploader = AitherUploader(
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


class AitherUploader(Unit3dBaseUploader):
    """Upload torrents to Aither"""

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
            tracker_name=TrackerSelection.AITHER,
            base_url="https://aither.cc",
            media_mode=media_mode,
            api_key=api_key,
            torrent_file=torrent_file,
            file_input=file_input,
            mediainfo_obj=mediainfo_obj,
            cat_enum=AitherCategory,
            res_enum=AitherResolution,
            type_enum=AitherType,
            timeout=timeout,
        )

    # def _get_category_id(self) -> str:  # TODO: detect TV here when support is added
    #     return super()._get_category_id()

    def _get_resolution_id(self) -> str:
        try:
            return super()._get_resolution_id()
        except TrackerError:
            return AitherResolution.RES_OTHER.value


class AitherSearch(Unit3dBaseSearch):
    """Search Aither"""

    __slots__ = ()

    def __init__(self, api_key: str, timeout: int = 60) -> None:
        super().__init__(
            tracker_name=TrackerSelection.AITHER,
            base_url="https://aither.cc",
            api_key=api_key,
            timeout=timeout,
        )
