import asyncio
import aiohttp
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Sequence
from src.logger.nfo_forge_logger import LOG
from src.packages.custom_types import ImageUploadData


class ImageDownloader:
    ACCEPTED_IMG_EXTS = {".png", ".jpg", ".jpeg"}

    __slots__ = ("url_data", "output_dir", "progress_cb", "batch_size", "max_retries")

    def __init__(
        self,
        url_data: Sequence[ImageUploadData],
        output_dir: Path,
        progress_cb: Callable[[float], None] | None = None,
        batch_size: int = 4,
        max_retries: int = 3,
    ) -> None:
        self.url_data = url_data
        self.output_dir = self._output_dir(output_dir)
        self.progress_cb = progress_cb
        self.batch_size = batch_size
        self.max_retries = max_retries

    def download_images(self) -> list[Path]:
        """Public method to start the image download"""
        async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(async_loop)
        images = async_loop.run_until_complete(self._download_images())
        async_loop.close()
        return images

    async def _download_images(self) -> list[Path]:
        """Async method that handles downloading images in batches"""
        images = self._parse_image_upload_data()
        if not images:
            raise ValueError("No valid images to download.")

        async with aiohttp.ClientSession() as session:
            total_files = len(images)
            downloaded_images = 0
            saved_files = []
            semaphore = asyncio.Semaphore(self.batch_size)

            for i in range(0, total_files, self.batch_size):
                batch = images[i : i + self.batch_size]
                tasks = [
                    self._retry_download(session, url, filename, semaphore)
                    for filename, url in batch
                ]
                results = await asyncio.gather(*tasks)

                for filename, content in results:
                    if content:
                        file_path = self.output_dir / filename
                        with open(file_path, "wb") as file:
                            file.write(content)
                        saved_files.append(file_path)
                        downloaded_images += 1

                        if self.progress_cb:
                            progress = (downloaded_images / total_files) * 100
                            self.progress_cb(progress)

            return saved_files

    async def _retry_download(
        self,
        session: aiohttp.ClientSession,
        url: str,
        filename: str,
        semaphore: asyncio.Semaphore,
    ) -> tuple[str, bytes | None]:
        """Attempts to download an image with retries"""
        for attempt in range(1, self.max_retries + 1):
            async with semaphore:
                async with session.get(url) as response:
                    if response.status == 200:
                        return filename, await response.read()
                    else:
                        LOG.warning(
                            LOG.LOG_SOURCE.BE,
                            f"Attempt {attempt}: Failed to download {url} (Status: {response.status})",
                        )

            await asyncio.sleep(2**attempt)

        LOG.warning(
            LOG.LOG_SOURCE.BE, f"Giving up on {url} after {self.max_retries} retries."
        )
        return filename, None

    def _parse_image_upload_data(self) -> list[tuple[str, str]]:
        """Parses image URLs from provided image data"""
        images = []

        for idx, item in enumerate(self.url_data, start=1):
            for url in filter(None, [item.url, item.medium_url]):
                url_lower = url.lower()
                for ext in self.ACCEPTED_IMG_EXTS:
                    if ext in url_lower:
                        images.append((f"dl_img_{idx}{ext}", url))
                        break
                else:
                    continue
                break

        return images

    @staticmethod
    def _output_dir(output_dir: Path) -> Path:
        """Ensure we have a clean directory to download images to"""
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        return output_dir
