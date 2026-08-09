from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from src.backend.image_host_uploading.api_key_upload import api_key_image_upload
from src.backend.image_host_uploading.base_image_host import (
    BaseImageHostUploader,
    ImageUploadRequest,
)
from src.packages.custom_types import ImageUploadData

URL = "https://api.imgbb.com/1/upload"


async def imgbb_upload(
    api_key: str,
    filepaths: Sequence[Path],
    batch_size: int = 4,
    progress_callback: Callable[[int], Awaitable[None]] | None = None,
) -> dict[int, ImageUploadData] | None:
    return await api_key_image_upload(
        url=URL,
        api_key=api_key,
        auth_mode="body",
        host_name="imgbb",
        filepaths=filepaths,
        batch_size=batch_size,
        progress_callback=progress_callback,
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
            )
            or {}
        )
