import asyncio
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, cast

import aiohttp

from nfoforge.backend.image_host_uploading.base_image_host import (
    BaseImageHostUploader,
    ImageUploadRequest,
)
from nfoforge.backend.image_host_uploading.retry import (
    RETRYABLE_STATUS,
    RetryableStatus,
    image_client_timeout,
    retry_image_upload,
)
from nfoforge.backend.upload_retry import IMAGE_UPLOAD_ATTEMPTS
from nfoforge.packages.custom_types import ImageUploadData

URL = "https://api.pixhost.to/images"


def _full_size_url(thumbnail_url: str) -> str:
    """Derive the full-size image URL from Pixhost's thumbnail URL."""
    return thumbnail_url.replace("https://t", "https://img").replace(
        "/thumbs/", "/images/"
    )


async def _upload_image(
    filepath: Path,
    cb: Callable[[int], Awaitable[None]] | None,
    idx: int,
    timeout: int | None = None,
    attempts: int = IMAGE_UPLOAD_ATTEMPTS,
) -> ImageUploadData:
    """Uploads a single image, retrying transient failures. Pixhost requires no
    authentication -- there is no API key to attach."""

    async def upload_once() -> ImageUploadData:
        # The session is opened per attempt: a retry is most often answering a
        # connection that went bad, and reusing its pool would hand the next
        # attempt the same broken one.
        async with aiohttp.ClientSession(
            timeout=image_client_timeout(timeout)
        ) as session:
            with open(filepath, "rb") as image_file:
                form_data = aiohttp.FormData()
                form_data.add_field("img", image_file, filename=filepath.name)
                form_data.add_field("content_type", "0")
                form_data.add_field("max_th_size", "350")

                async with session.post(URL, data=form_data) as response:
                    if response.status in RETRYABLE_STATUS:
                        raise RetryableStatus(response.status, response.reason)
                    if response.status != 200:
                        return ImageUploadData(None, None)
                    response_data = cast(dict[str, Any], await response.json())

                thumbnail_url = response_data.get("th_url", "")
                if not thumbnail_url:
                    return ImageUploadData(None, None)
                if cb:
                    await cb(idx)
                return ImageUploadData(_full_size_url(thumbnail_url), thumbnail_url)

    result = await retry_image_upload(
        upload_once, host_name="Pixhost", attempts=attempts
    )
    return result if result is not None else ImageUploadData(None, None)


async def _upload_batch(
    filepaths: Sequence[Path],
    start_index: int,
    cb: Callable[[int], Awaitable[None]] | None,
    timeout: int | None = None,
    attempts: int = IMAGE_UPLOAD_ATTEMPTS,
) -> dict[int, ImageUploadData]:
    tasks = [
        asyncio.create_task(
            _upload_image(filepath, cb, start_index + i + 1, timeout, attempts)
        )
        for i, filepath in enumerate(filepaths)
    ]
    results = await asyncio.gather(*tasks)
    return {start_index + i: result for i, result in enumerate(results)}


async def pixhost_upload(
    filepaths: Sequence[Path],
    batch_size: int = 4,
    progress_callback: Callable[[int], Awaitable[None]] | None = None,
    timeout: int | None = None,
    attempts: int = IMAGE_UPLOAD_ATTEMPTS,
) -> dict[int, ImageUploadData] | None:
    if not filepaths:
        return {}
    filepaths = sorted(filepaths)

    results: dict[int, ImageUploadData] = {}
    tasks: list[asyncio.Task[dict[int, ImageUploadData]]] = []
    for i in range(0, len(filepaths), batch_size):
        batch = filepaths[i : i + batch_size]
        task = asyncio.create_task(
            _upload_batch(batch, i, progress_callback, timeout, attempts)
        )
        tasks.append(task)

    batch_results_list = await asyncio.gather(*tasks)
    for batch_results in batch_results_list:
        results.update(batch_results)

    return results


class PixhostUploader(BaseImageHostUploader):
    """Uploader for Pixhost. Requires no credentials -- uploads are anonymous."""

    __slots__ = ()

    async def upload(self, request: ImageUploadRequest) -> dict[int, ImageUploadData]:
        """Upload images to Pixhost."""
        return (
            await pixhost_upload(
                filepaths=request.filepaths,
                batch_size=request.batch_size,
                progress_callback=request.progress_callback,
                timeout=request.timeout,
                attempts=request.attempts,
            )
            or {}
        )
