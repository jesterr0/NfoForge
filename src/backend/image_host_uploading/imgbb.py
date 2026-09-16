from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from src.backend.image_host_uploading.api_key_upload import api_key_image_upload
from src.backend.image_host_uploading.base_image_host import (
    BaseImageHostUploader,
    ImageUploadRequest,
)
from src.backend.upload_retry import IMAGE_UPLOAD_ATTEMPTS
from src.packages.custom_types import ImageUploadData

URL = "https://api.imgbb.com/1/upload"


async def imgbb_upload(
    api_key: str,
    filepaths: Sequence[Path],
    batch_size: int = 4,
    progress_callback: Callable[[int], Awaitable[None]] | None = None,
    timeout: int | None = None,
    attempts: int = IMAGE_UPLOAD_ATTEMPTS,
) -> dict[int, ImageUploadData] | None:
    return await api_key_image_upload(
        url=URL,
        api_key=api_key,
        auth_mode="body",
        host_name="imgbb",
        filepaths=filepaths,
        batch_size=batch_size,
        progress_callback=progress_callback,
        timeout=timeout,
        attempts=attempts,
    )


class ImageBBUploader(BaseImageHostUploader):
    """Uploader for ImageBB."""

    __slots__ = ("api_key",)

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def upload(self, request: ImageUploadRequest) -> dict[int, ImageUploadData]:
        """Upload images to ImageBB."""
        return (
            await imgbb_upload(
                api_key=self.api_key,
                filepaths=request.filepaths,
                batch_size=request.batch_size,
                progress_callback=request.progress_callback,
                timeout=request.timeout,
                attempts=request.attempts,
            )
            or {}
        )
