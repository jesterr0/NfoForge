import aiohttp
import asyncio
import base64
from collections.abc import Callable, Sequence, Awaitable
from os import PathLike
from pathlib import Path

from src.backend.image_host_uploading.base_image_host import BaseImageHostUploader
from src.packages.custom_types import ImageUploadData
from src.exceptions import ImageUploadError


async def upload_image(url: str, api_key: str, image_data: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url, data={"key": api_key, "image": image_data}
        ) as response:
            response_json = await response.json()
            return response_json


async def _imgbb_upload_batch(
    api_key: str,
    filepaths: Sequence[Path],
    start_index: int,
    cb: Callable[[int], Awaitable] | None = None,
) -> dict[int, ImageUploadData]:
    async def upload_single_image(
        url: str, filepath: PathLike, index: int
    ) -> tuple[int, ImageUploadData]:
        with open(filepath, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode("utf-8")
            response = await upload_image(url, api_key, image_data)
            data = response.get("data", {})
            image_data = ImageUploadData(
                data.get("image", {}).get("url", ""),
                data.get("medium", {}).get("url", ""),
            )
            if cb:
                await cb(index + 1)
            return index, image_data

    URL = "https://api.imgbb.com/1/upload"
    tasks = []
    for i, filepath in enumerate(filepaths):
        task = asyncio.create_task(upload_single_image(URL, filepath, start_index + i))
        tasks.append(task)

    batch_results = await asyncio.gather(*tasks)
    return {index: result for index, result in batch_results}


async def imgbb_upload(
    api_key: str,
    filepaths: Sequence[Path],
    batch_size: int = 4,
    progress_callback: Callable[[int], Awaitable] | None = None,
) -> dict[int, ImageUploadData] | None:
    if not api_key:
        raise ImageUploadError("You are required to have an API key")

    if not filepaths:
        return {}
    filepaths = sorted(filepaths)

    results = {}
    tasks = []
    for i in range(0, len(filepaths), batch_size):
        batch = filepaths[i : i + batch_size]
        task = asyncio.create_task(
            _imgbb_upload_batch(api_key, batch, i, progress_callback)
        )
        tasks.append(task)

    batch_results_list = await asyncio.gather(*tasks)
    for batch_results in batch_results_list:
        results.update(batch_results)

    return results


class ImageBBUploader(BaseImageHostUploader):
    """Uploader for ImageBB."""

    __slots__ = ("api_key",)

    def __init__(self, api_key: str, url: str) -> None:
        self.api_key = api_key

    async def upload(
        self,
        filepaths: Sequence[Path],
        batch_size: int = 4,
        progress_callback: Callable[[int], Awaitable] | None = None,
    ) -> dict[int, ImageUploadData] | None:
        """Upload images to ImageBB."""
        return await imgbb_upload(
            api_key=self.api_key,
            filepaths=filepaths,
            batch_size=4,
            progress_callback=progress_callback,
        )
