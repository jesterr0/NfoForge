from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from nfoforge.backend.upload_retry import IMAGE_UPLOAD_ATTEMPTS
from nfoforge.packages.custom_types import ImageUploadData

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
    timeout: int | None = None
    """Per-request connect/read budget in seconds; None keeps the library default.

    Both this and `attempts` carry defaults so that a plugin-supplied uploader
    written before they existed still receives a valid request, and one that
    ignores them behaves exactly as it did.
    """

    attempts: int = IMAGE_UPLOAD_ATTEMPTS
    """Automatic attempts per image before the failure is reported upward."""


class BaseImageHostUploader(ABC):
    """Abstract base class for image host uploaders"""

    @abstractmethod
    async def upload(self, request: ImageUploadRequest) -> dict[int, ImageUploadData]:
        """Uploads images and reports progress"""
        raise NotImplementedError
