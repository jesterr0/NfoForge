import asyncio
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, cast

import aiohttp

from src.backend.image_host_uploading.base_image_host import (
    BaseImageHostUploader,
    ImageUploadRequest,
)
from src.logger.nfo_forge_logger import LOG
from src.packages.custom_types import ImageUploadData

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
    retries: int = 3,
) -> ImageUploadData:
    """Uploads a single image with retries and proper error handling. Pixhost
    requires no authentication -- there is no API key to attach."""
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                with open(filepath, "rb") as image_file:
                    form_data = aiohttp.FormData()
                    form_data.add_field("img", image_file, filename=filepath.name)
                    form_data.add_field("content_type", "0")
                    form_data.add_field("max_th_size", "350")

                    async with session.post(URL, data=form_data) as response:
                        if response.status == 200:
                            response_data = cast(dict[str, Any], await response.json())
                        elif response.status in {429, 500, 502, 503, 504}:
                            await asyncio.sleep(2**attempt)
                            continue
                        else:
                            return ImageUploadData(None, None)

                    thumbnail_url = response_data.get("th_url", "")
                    if not thumbnail_url:
                        return ImageUploadData(None, None)
                    if cb:
                        await cb(idx)
                    return ImageUploadData(_full_size_url(thumbnail_url), thumbnail_url)

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(2**attempt)
            else:
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"Pixhost: upload failed after {retries} attempts: {e}",
                )

    return ImageUploadData(None, None)


async def _upload_batch(
    filepaths: Sequence[Path],
    start_index: int,
    cb: Callable[[int], Awaitable[None]] | None,
) -> dict[int, ImageUploadData]:
    tasks = [
        asyncio.create_task(_upload_image(filepath, cb, start_index + i + 1))
        for i, filepath in enumerate(filepaths)
    ]
    results = await asyncio.gather(*tasks)
    return {start_index + i: result for i, result in enumerate(results)}


async def pixhost_upload(
    filepaths: Sequence[Path],
    batch_size: int = 4,
    progress_callback: Callable[[int], Awaitable[None]] | None = None,
) -> dict[int, ImageUploadData] | None:
    if not filepaths:
        return {}
    filepaths = sorted(filepaths)

    results: dict[int, ImageUploadData] = {}
    tasks: list[asyncio.Task[dict[int, ImageUploadData]]] = []
    for i in range(0, len(filepaths), batch_size):
        batch = filepaths[i : i + batch_size]
        task = asyncio.create_task(_upload_batch(batch, i, progress_callback))
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
            )
            or {}
        )
