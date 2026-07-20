from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from src.packages.custom_types import ImageUploadData

ImageUploadProgressCallback = Callable[[int], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ImageUploadRequest:
    """Provider-neutral image upload input."""

    filepaths: Sequence[Path]
    batch_size: int = 4
    progress_callback: ImageUploadProgressCallback | None = None
    album_name: str | None = None
    title: str | None = None
    thumb_width: int = 350
    square_thumbs: bool = False
    adult: bool = False
    comments_enabled: bool = False


class BaseImageHostUploader(ABC):
    """Abstract base class for image host uploaders"""

    @abstractmethod
    async def upload(self, request: ImageUploadRequest) -> dict[int, ImageUploadData]:
        """Uploads images and reports progress"""
        raise NotImplementedError
