from pathlib import Path

from pymediainfo import MediaInfo
from typing_extensions import override

from src.backend.trackers.unit3d_base import Unit3dBaseSearch, Unit3dBaseUploader
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.onlyencodes import (
    OnlyEncodesCategory,
    OnlyEncodesResolution,
    OnlyEncodesType,
)
from src.exceptions import TrackerError
from src.payloads.media_search import MediaSearchPayload


def oe_uploader(
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
    uploader = OnlyEncodesUploader(
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


class OnlyEncodesUploader(Unit3dBaseUploader):
    """Upload torrents to OnlyEncodes"""

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
            tracker_name=TrackerSelection.ONLY_ENCODES,
            base_url="https://onlyencodes.cc",
            media_type=media_type,
            api_key=api_key,
            torrent_file=torrent_file,
            file_input=file_input,
            mediainfo_obj=mediainfo_obj,
            cat_enum=OnlyEncodesCategory,
            res_enum=OnlyEncodesResolution,
            type_enum=OnlyEncodesType,
            timeout=timeout,
        )

    @override
    def _get_type_id(self) -> str:
        # try to get type from base class and match with known types
        try:
            type_id = super()._get_type_id()
            return OnlyEncodesType(type_id).value
        except (TrackerError, ValueError):
            pass

        # fallback by checking the file name for known codecs
        lowered_file_input = self.file_input.stem.lower()
        for codec, enum in [
            ("x265", OnlyEncodesType.ENCODE_X265),
            ("av1", OnlyEncodesType.ENCODE_AV1),
            ("x264", OnlyEncodesType.ENCODE_X264),
        ]:
            if codec in lowered_file_input:
                return enum.value

        raise TrackerError("Failed to determine the correct type for OnlyEncodes")


class OnlyEncodesSearch(Unit3dBaseSearch):
    """Search OnlyEncodes"""

    __slots__ = ()

    def __init__(self, api_key: str, timeout: int = 60) -> None:
        super().__init__(
            tracker_name=TrackerSelection.ONLY_ENCODES,
            base_url="https://onlyencodes.cc",
            api_key=api_key,
            timeout=timeout,
        )
