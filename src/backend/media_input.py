from pathlib import Path
from pymediainfo import MediaInfo


class MediaInputBackEnd:
    def get_media_info(self, file_input: Path) -> MediaInfo | None:
        data = MediaInfo.parse(file_input)
        return data if isinstance(data, MediaInfo) else None
