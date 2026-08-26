from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from src.backend.image_host_uploading.api_key_upload import api_key_image_upload
from src.backend.image_host_uploading.base_image_host import (
    BaseImageHostUploader,
    ImageUploadRequest,
)
from src.packages.custom_types import ImageUploadData


def _create_api_url(image_url: str) -> str:
    """Create the API URL for Chevereto V4."""
    if not image_url.endswith("api/1/upload") and not image_url.endswith(
        "api/1/upload/"
    ):
        if not image_url.endswith("/"):
            image_url = image_url + "/"
        image_url = image_url + "api/1/upload"
    return image_url


async def chevereto_v4_upload(
    api_key: str,
    url: str,
    filepaths: Sequence[Path],
    batch_size: int = 4,
    progress_callback: Callable[[int], Awaitable[None]] | None = None,
    host_name: str = "Chevereto v4",
) -> dict[int, ImageUploadData] | None:
    """Upload images to a Chevereto V4 site.

    `auth_mode="both"`: Chevereto accepts the API key as a ``key`` form field
    or an ``X-API-Key`` header, and which one a given site honours varies by
    version and configuration (ptscreens.com documents only the header). Both
    are sent, and the site ignores the one it does not use.
    """
    return await api_key_image_upload(
        url=_create_api_url(url),
        api_key=api_key,
        auth_mode="both",
        host_name=host_name,
        filepaths=filepaths,
        batch_size=batch_size,
        progress_callback=progress_callback,
    )


class CheveretoV4Uploader(BaseImageHostUploader):
    """Uploader for one configured Chevereto V4 site."""

    __slots__ = ("api_key", "host_name", "url")

    def __init__(self, api_key: str, url: str, host_name: str = "Chevereto v4") -> None:
        self.api_key = api_key
        self.url = url
        self.host_name = host_name

    async def upload(self, request: ImageUploadRequest) -> dict[int, ImageUploadData]:
        """Upload images to Chevereto V4."""
        return (
            await chevereto_v4_upload(
                api_key=self.api_key,
                url=self.url,
                filepaths=request.filepaths,
                batch_size=request.batch_size,
                progress_callback=request.progress_callback,
                host_name=self.host_name,
            )
            or {}
        )
