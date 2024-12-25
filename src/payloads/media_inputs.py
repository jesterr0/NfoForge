from dataclasses import dataclass
from pathlib import Path

from pymediainfo import MediaInfo


@dataclass(slots=True)
class MediaInputPayload:
    script_file: Path | None = None
    source_file: Path | None = None
    source_file_dir: Path | None = None
    source_file_mi_obj: MediaInfo | None = None
    encode_file: Path | None = None
    encode_file_dir: Path | None = None
    encode_file_mi_obj: MediaInfo | None = None
    renamed_file: Path | None = None

    def reset(self) -> None:
        self.script_file = None
        self.source_file = None
        self.source_file_dir = None
        self.source_file_mi_obj = None
        self.encode_file = None
        self.encode_file_dir = None
        self.encode_file_mi_obj = None
        self.renamed_file = None
