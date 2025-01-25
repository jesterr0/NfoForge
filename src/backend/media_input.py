from collections.abc import Sequence
from pathlib import Path
from pymediainfo import MediaInfo


class MediaInputBackEnd:
    __slots__ = ()

    @staticmethod
    def get_media_info(file_input: Path) -> MediaInfo | None:
        data = MediaInfo.parse(file_input)
        return data if isinstance(data, MediaInfo) else None

    @staticmethod
    def get_media_info_files(files: Sequence[Path]) -> list[MediaInfo]:
        media_info_data = []
        for media_file in files:
            media_info_data.append(MediaInputBackEnd.get_media_info(media_file))
        return media_info_data
