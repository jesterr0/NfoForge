import asyncio
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

import aiohttp

from src.backend.image_host_uploading.base_image_host import BaseImageHostUploader
from src.exceptions import ImageUploadError
from src.logger.nfo_forge_logger import LOG
from src.packages.custom_types import ImageUploadData

PTPIMG_BASE_URL = "https://ptpimg.me"


async def upload_image(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict[str, str],
    data: dict[str, str],
    file_path: Path,
    retries: int = 3,
) -> dict | str:
    """Uploads an image using aiohttp with retries and proper error handling."""
    for attempt in range(retries):
        try:
            form_data = aiohttp.FormData()
            with open(file_path, "rb") as image_file:
                form_data.add_field(
                    "file-upload[0]", image_file, filename=file_path.name
                )
                form_data.add_field("format", "json")
                form_data.add_field("api_key", data["api_key"])

                async with session.post(
                    url, headers=headers, data=form_data
                ) as response:
                    if response.status == 200:
                        response_json = await response.json()
                        result = response_json[0]
                        return f"{PTPIMG_BASE_URL}/{result['code']}.{result['ext']}"

                    if response.status in {429, 500, 502, 503, 504}:
                        await asyncio.sleep(2**attempt)
                        continue
                    else:
                        return {
                            "status": response.status,
                            "reason": response.reason,
                        }

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(2**attempt)
            else:
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"ptpimg: upload failed after {retries} attempts: {e}",
                )

    return {"status": "Failed", "reason": "Failure on retry"}


async def _ptpimg_upload_batch(
    api_key: str,
    filepaths: Sequence[Path],
    start_index: int,
    cb: Callable[[int], Awaitable] | None = None,
) -> dict[int, ImageUploadData]:
    async def upload_single_image(filepath: Path, index: int):
        response = await upload_image(session, url, headers, payload, filepath)
        if not isinstance(response, str):
            raise ImageUploadError(
                f"Failure uploading image: {response.get('status')} ({response.get('reason')})"
            )
        image_data = ImageUploadData(response, None)
        if cb:
            await cb(index + 1)
        return index, image_data

    url = f"{PTPIMG_BASE_URL}/upload.php"
    headers = {"referer": f"{PTPIMG_BASE_URL}/index.php"}
    payload = {"api_key": api_key}

    tasks = []
    async with aiohttp.ClientSession() as session:
        for i, filepath in enumerate(filepaths):
            task = asyncio.create_task(upload_single_image(filepath, start_index + i))
            tasks.append(task)

        batch_results_list = await asyncio.gather(*tasks)

    return {index: result for index, result in batch_results_list}


async def ptpimg_upload(
    api_key: str,
    filepaths: Sequence[Path],
    batch_size: int = 4,
    progress_callback: Callable[[int], Awaitable] | None = None,
) -> dict[int, ImageUploadData] | None:
    if not api_key:
        raise ValueError("You are required to have an API key")

    if not filepaths:
        return {}
    filepaths = sorted(filepaths)

    results = {}
    tasks = []
    for i in range(0, len(filepaths), batch_size):
        batch = filepaths[i : i + batch_size]
        task = asyncio.create_task(
            _ptpimg_upload_batch(api_key, batch, i, progress_callback)
        )
        tasks.append(task)

    batch_results_list = await asyncio.gather(*tasks)
    for batch_results in batch_results_list:
        results.update(batch_results)

    return results


class PTPIMGUploader(BaseImageHostUploader):
    """Uploader for PTPIMG."""

    __slots__ = ("api_key",)

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def upload(
        self,
        filepaths: Sequence[Path],
        batch_size: int = 4,
        progress_callback: Callable[[int], Awaitable] | None = None,
    ) -> dict[int, ImageUploadData] | None:
        """Upload images to ImageBB."""
        return await ptpimg_upload(
            api_key=self.api_key,
            filepaths=filepaths,
            batch_size=4,
            progress_callback=progress_callback,
        )
