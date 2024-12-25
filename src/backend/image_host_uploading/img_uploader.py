import asyncio
from collections.abc import Sequence
from os import PathLike
from pathlib import Path

from PySide6.QtCore import SignalInstance

from src.config.config import Config
from src.exceptions import ImageUploadError
from src.logger.nfo_forge_logger import LOG
from src.packages.custom_types import ImageUploadData
from src.backend.image_host_uploading.chevereto_v3 import chevereto_v3_upload
from src.backend.image_host_uploading.chevereto_v4 import chevereto_v4_upload
from src.backend.image_host_uploading.img_box import image_box_upload
from src.backend.image_host_uploading.imgbb import imgbb_upload


class ImageUploader:
    def __init__(self, config: Config, progress_signal: SignalInstance) -> None:
        """Initialize the ImageUploader with the given configuration"""
        self.config = config
        self.progress_signal = progress_signal
        self._total_files = 0
        self._remaining = 0
        self._lock = asyncio.Lock()
        LOG.debug(LOG.LOG_SOURCE.BE, "Initiating ImageUploader")

    def chevereto_v3(
        self,
        filepaths: Sequence[PathLike[str] | Path | str],
        batch_size: int = 4,
        album_name: str | None = None,
    ) -> dict[int, ImageUploadData] | None:
        """Upload images to Chevereto V3"""
        LOG.info(LOG.LOG_SOURCE.BE, "Utilizing Chevereto V3")

        self._total_files = self._remaining = len(filepaths)

        base_url = self.config.cfg_payload.chevereto_v3.base_url
        user = self.config.cfg_payload.chevereto_v3.user
        password = self.config.cfg_payload.chevereto_v3.password
        if not base_url or not user or not password:
            raise ImageUploadError("Base URL, user, and password is required")

        results = asyncio.run(
            chevereto_v3_upload(
                base_url=base_url,
                user=user,
                password=password,
                filepaths=[Path(x) for x in filepaths if x],
                batch_size=batch_size,
                album_name=album_name,
                cb=self.upload_progress,
            )
        )
        return results

    def chevereto_v4(
        self, filepaths: Sequence[PathLike[str] | Path | str], batch_size: int = 4
    ) -> dict[int, ImageUploadData] | None:
        """Upload images to Chevereto V4"""
        LOG.info(LOG.LOG_SOURCE.BE, "Utilizing Chevereto V4")

        api_key = self.config.cfg_payload.chevereto_v4.api_key
        url = self.config.cfg_payload.chevereto_v4.base_url
        if not api_key or not url:
            raise ImageUploadError("API key and URL is required")

        self._total_files = self._remaining = len(filepaths)
        results = asyncio.run(
            chevereto_v4_upload(
                api_key=api_key,
                url=url,
                filepaths=[Path(x) for x in filepaths if x],
                batch_size=batch_size,
                cb=self.upload_progress,
            )
        )
        return results

    def img_box(
        self,
        filepaths: Sequence[PathLike[str] | Path | str],
        title: str | None = None,
        thumb_width: int = 350,
        square_thumbs: bool = False,
        adult: bool = False,
        comments_enabled: bool = False,
        batch_size: int = 4,
    ) -> dict[int, ImageUploadData] | None:
        """Upload images to ImageBox"""
        LOG.info(LOG.LOG_SOURCE.BE, "Utilizing ImageBox")

        self._total_files = self._remaining = len(filepaths)
        results = asyncio.run(
            image_box_upload(
                filepaths=[Path(x) for x in filepaths if x],
                title=title,
                thumb_width=thumb_width,
                square_thumbs=square_thumbs,
                adult=adult,
                comments_enabled=comments_enabled,
                batch_size=batch_size,
                cb=self.upload_progress,
            )
        )
        return results

    def imgbb(
        self,
        filepaths: Sequence[PathLike[str] | Path | str],
        batch_size: int = 4,
    ) -> dict[int, ImageUploadData] | None:
        """Upload images to ImageBB"""
        LOG.info(LOG.LOG_SOURCE.BE, "Utilizing ImageBB")

        self._total_files = self._remaining = len(filepaths)

        api_key = self.config.cfg_payload.image_bb.api_key
        if not api_key:
            raise ImageUploadError("API key is required")

        results = asyncio.run(
            imgbb_upload(
                api_key=api_key,
                filepaths=[Path(x) for x in filepaths if x],
                batch_size=batch_size,
                cb=self.upload_progress,
            )
        )
        return results

    async def upload_progress(self, idx: int) -> None:
        """Callback function to track the progress of image uploads"""
        async with self._lock:
            self._remaining -= 1
            if self.progress_signal:
                image_progress = f"IDX={idx} Total Files={self._total_files} Remaining={self._remaining}"
                LOG.debug(LOG.LOG_SOURCE.BE, image_progress)
                self.progress_signal.emit(
                    image_progress,
                    int(
                        ((self._total_files - self._remaining) / self._total_files)
                        * 100
                    ),
                )
