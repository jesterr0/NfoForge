from pathlib import Path
from pymediainfo import MediaInfo

from src.backend.trackers import Unit3dBaseSearch, Unit3dBaseUploader
from src.enums.trackers.huno import HunoResolution, HunoType, HunoCategory
from src.payloads.media_search import MediaSearchPayload


def huno_uploader(
    api_key: str,
    torrent_file: Path,
    file_input: Path,
    tracker_title: str | None,
    nfo: str,
    internal: bool,
    anonymous: bool,
    stream_optimized: bool,
    mediainfo_obj: MediaInfo,
    media_search_payload: MediaSearchPayload,
    timeout: int = 60,
) -> bool | None:
    torrent_file = Path(torrent_file)
    file_input = Path(file_input)
    uploader = HunoUploader(
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
        personal_release=None,
        stream_optimized=stream_optimized,
        opt_in_to_mod_queue=None,
        featured=None,
        free=None,
        double_up=None,
        sticky=None,
    )
    return upload


class HunoUploader(Unit3dBaseUploader):
    """Upload torrents to HUNO"""

    __slots__ = ()

    def __init__(
        self,
        api_key: str,
        torrent_file: Path,
        file_input: Path,
        mediainfo_obj: MediaInfo,
        timeout: int = 60,
    ) -> None:
        super().__init__(
            tracker_name="HUNO",
            base_url="https://hawke.uno",
            api_key=api_key,
            torrent_file=torrent_file,
            file_input=file_input,
            mediainfo_obj=mediainfo_obj,
            cat_enum=HunoCategory,
            res_enum=HunoResolution,
            type_enum=HunoType,
            timeout=timeout,
        )


class HunoSearch(Unit3dBaseSearch):
    """Search HUNO"""

    __slots__ = ()

    def __init__(self, api_key: str, timeout: int = 60) -> None:
        super().__init__(
            tracker_name="HUNO",
            base_url="https://hawke.uno",
            api_key=api_key,
            timeout=timeout,
        )
