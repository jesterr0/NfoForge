from pathlib import Path
from typing import NamedTuple

from src.enums.image_host import ImageHost, ImageSource


class SubNames(NamedTuple):
    source: str
    encode: str


class CropValues(NamedTuple):
    top: int
    bottom: int
    left: int
    right: int


class AdvancedResize(NamedTuple):
    src_left: float
    src_top: float
    src_width: float
    src_height: float


class ImageUploadData(NamedTuple):
    url: str | None
    medium_url: str | None


class ImageUploadFromTo(NamedTuple):
    img_from: ImageSource
    img_to: ImageSource | ImageHost


class RenameNormalization(NamedTuple):
    normalized: str
    re_gex: tuple[str, ...]


class ComparisonPair(NamedTuple):
    source: Path
    media: Path
    script: Path | None
