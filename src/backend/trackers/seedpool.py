from pathlib import Path

from pymediainfo import MediaInfo

from src.backend.trackers.unit3d_base import Unit3dBaseSearch, Unit3dBaseUploader
from src.backend.trackers.utils import dot_separate_title
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.seedpool import (
    SeedPoolCategory,
    SeedPoolResolution,
    SeedPoolType,
)
from src.payloads.media_search import MediaSearchPayload


def sp_uploader(
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
    uploader = SeedPoolUploader(
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


class SeedPoolUploader(Unit3dBaseUploader):
    """Upload torrents to SeedPool"""

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
            tracker_name=TrackerSelection.SEEDPOOL,
            base_url=TrackerSelection.SEEDPOOL.get_root_url(),
            media_type=media_type,
            api_key=api_key,
            torrent_file=torrent_file,
            input_path=input_path,
            mediainfo_obj=mediainfo_obj,
            cat_enum=SeedPoolCategory,
            res_enum=SeedPoolResolution,
            type_enum=SeedPoolType,
            timeout=timeout,
        )

    @staticmethod
    def generate_release_title(release_title: str) -> str:
        """SeedPool names uploads after the release, not in prose.

        Every other UNIT3D tracker here wants the spaced form, so the base
        class strips periods; SeedPool is the exception and wants them. Both
        reference implementations agree: Upload Assistant's SP uploader sends
        the input's own name with spaces turned into periods, and upbrr's
        seedpool profile resolves to the source release name, with expected
        values like ``Example.Release.2026.1080p.WEB-DL.H.264-GRP``.

        The base class was flattening the filename fallback -- which is the
        release name already -- into the spaced form no other tracker here
        would have wanted.
        """
        return dot_separate_title(release_title)


class SeedPoolSearch(Unit3dBaseSearch):
    """Search SeedPool"""

    __slots__ = ()

    def __init__(self, api_key: str, timeout: int = 60) -> None:
        super().__init__(
            tracker_name=TrackerSelection.SEEDPOOL,
            base_url=TrackerSelection.SEEDPOOL.get_root_url(),
            api_key=api_key,
            timeout=timeout,
        )
