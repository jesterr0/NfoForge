import asyncio
import base64
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

import aiohttp

from src.backend.image_host_uploading.base_image_host import BaseImageHostUploader
from src.exceptions import ImageUploadError
from src.logger.nfo_forge_logger import LOG
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


async def upload_image(
    url: str, api_key: str, image_data: str, retries: int = 3
) -> dict:
    """Upload a single image to the specified URL using the provided API key with retries."""
    async with aiohttp.ClientSession() as session:
        for attempt in range(retries):
            try:
                async with session.post(
                    url, data={"key": api_key, "image": image_data}
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status in {429, 500, 502, 503, 504}:
                        await asyncio.sleep(2**attempt)
                    else:
                        break
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < retries - 1:
                    await asyncio.sleep(2**attempt)
                else:
                    LOG.warning(
                        LOG.LOG_SOURCE.BE,
                        f"Chevereto V4: upload failed after {retries} attempts: {e}",
                    )

    return {}


async def _chevereto_V4_upload_batch(
    api_key: str,
    url: str,
    batch: Sequence[Path],
    start_index: int,
    cb: Callable[[int], Awaitable] | None = None,
) -> dict[int, ImageUploadData]:
    """Upload a batch of images to Chevereto V4."""
    batch_results = {}

    for i, filepath in enumerate(batch):
        with open(filepath, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode("utf-8")
            response = await upload_image(url, api_key, image_data)
            data = response.get("data", {})
            batch_results[start_index + i] = ImageUploadData(
                data.get("url", ""), data.get("medium", {}).get("url", "")
            )
            if cb:
                await cb((start_index + i) + 1)

    return batch_results


async def chevereto_v4_upload(
    api_key: str,
    url: str,
    filepaths: Sequence[Path],
    batch_size: int = 4,
    progress_callback: Callable[[int], Awaitable] | None = None,
) -> dict[int, ImageUploadData] | None:
    """Upload images to Chevereto V4 in batches."""
    if not api_key:
        raise ImageUploadError("You are required to have an API key")

    if not filepaths:
        return {}
    filepaths = sorted(filepaths)

    url = _create_api_url(url)
    total_files = len(filepaths)
    results = {}

    tasks = []
    for i in range(0, total_files, batch_size):
        batch = filepaths[i : i + batch_size]
        task = _chevereto_V4_upload_batch(api_key, url, batch, i, progress_callback)
        tasks.append(task)

    batch_results_list = await asyncio.gather(*tasks)

    for batch_results in batch_results_list:
        results.update(batch_results)

    return results


class CheveretoV4Uploader(BaseImageHostUploader):
    """Uploader for Chevereto V4."""

    __slots__ = ("api_key", "url")

    def __init__(self, api_key: str, url: str) -> None:
        self.api_key = api_key
        self.url = url

    async def upload(
        self,
        filepaths: Sequence[Path],
        progress_callback: Callable[[int], Awaitable] | None = None,
    ) -> dict[int, ImageUploadData] | None:
        """Upload images to Chevereto V4."""
        return await chevereto_v4_upload(
            api_key=self.api_key,
            url=self.url,
            filepaths=filepaths,
            batch_size=4,
            progress_callback=progress_callback,
        )
