import asyncio
from collections.abc import Sequence, Callable, Awaitable
from pathlib import Path
from pyimgbox import Gallery as ImgBoxGallery, Submission

from src.backend.image_host_uploading.base_image_host import BaseImageHostUploader
from src.packages.custom_types import ImageUploadData


async def _img_box_upload_batch(
    gallery: ImgBoxGallery,
    filepaths: Sequence[Path],
    start_index: int,
    cb: Callable[[int], Awaitable] | None = None,
) -> dict[int, ImageUploadData]:
    """
    Uploads a batch of images to ImgBox.

    Example Output (before converting to ImageUploadData):
        >>> {
        ...     0: Submission(
        ...         success=True,
        ...         filepath='path/01_output.png',
        ...         filename='01_output.png',
        ...         image_url='https://images2.imgbox.com/2b/a5/FKz3MCE3_o.png',
        ...         thumbnail_url='https://thumbs2.imgbox.com/2b/a5/FKz3MCE3_t.png',
        ...         web_url='https://imgbox.com/FKz3MCE3',
        ...         gallery_url='https://imgbox.com/g/OJ8zOPVcHi',
        ...         edit_url='https://imgbox.com/upload/edit/824171454/MpUyo3nn75ZcRJar'
        ...     ),
        ...     1: Submission(...)
        ... }

    """

    async def upload_single_image(
        gallery: ImgBoxGallery,
        cb: Callable[[int], Awaitable] | None,
        filepath: Path,
        index: int,
        retries: int = 3,
    ) -> tuple[int, ImageUploadData]:
        """Uploads a single image with retries and exponential backoff."""
        for attempt in range(retries):
            try:
                submission: Submission = await gallery.upload(filepath)
                if not submission or not submission.get("image_url"):
                    raise ValueError(f"Upload failed for {filepath}")

                image_data = ImageUploadData(
                    submission.get("image_url", ""), submission.get("thumbnail_url", "")
                )

                if cb:
                    await cb(index + 1)

                return index, image_data

            except Exception:
                if attempt < retries - 1:
                    wait_time = 2**attempt
                    await asyncio.sleep(wait_time)

        return index, ImageUploadData(None, None)

    tasks = [
        asyncio.create_task(upload_single_image(gallery, cb, filepath, start_index + i))
        for i, filepath in enumerate(filepaths)
    ]

    batch_results = await asyncio.gather(*tasks)
    return {index: result for index, result in batch_results}


async def image_box_upload(
    filepaths: Sequence[Path],
    title: str | None = None,
    thumb_width: int = 350,
    square_thumbs: bool = False,
    adult: bool = False,
    comments_enabled: bool = False,
    batch_size: int = 4,
    progress_callback: Callable[[int], Awaitable] | None = None,
) -> dict[int, ImageUploadData] | None:
    """
    Uploads images to a gallery in batches and returns the upload results.

    Args:
        filepaths (Iterable[PathLike[str]]): List of file paths to the images to be uploaded.
        title (Optional[str], optional): Title of the gallery. Defaults to None.
        thumb_width (int, optional): Width of the thumbnails. Defaults to 350.
        square_thumbs (bool, optional): Whether thumbnails should be square. Defaults to False.
        adult (bool, optional): Whether the gallery contains adult content. Defaults to False.
        comments_enabled (bool, optional): Whether comments are enabled for the gallery. Defaults to False.
        batch_size (int, optional): Number of images to upload in each batch. Defaults to 5.
        progress_callback (Callable[[int], None]): Callback to print progress.

    Returns:
        Optional[Dict[int, ImageUploadData]]: A dictionary with indices as keys and ImageUploadData objects as values.
    """
    if not filepaths:
        return {}

    filepaths = sorted(filepaths)
    image_data = {}
    start_index = 0

    async with ImgBoxGallery(
        title=title if title else None,
        thumb_width=thumb_width,
        square_thumbs=square_thumbs,
        adult=adult,
        comments_enabled=comments_enabled,
    ) as gallery:
        for i in range(0, len(filepaths), batch_size):
            batch = filepaths[i : i + batch_size]
            batch_results = await _img_box_upload_batch(
                gallery, batch, start_index, progress_callback
            )
            image_data.update(batch_results)
            start_index += len(batch)

    return image_data


class ImageBoxUploader(BaseImageHostUploader):
    """Uploader for ImageBox."""

    __slots__ = ()

    async def upload(
        self,
        filepaths: Sequence[Path],
        title: str | None = None,
        thumb_width: int = 350,
        square_thumbs: bool = False,
        adult: bool = False,
        comments_enabled: bool = False,
        batch_size: int = 4,
        progress_callback: Callable[[int], Awaitable] | None = None,
    ) -> dict[int, ImageUploadData] | None:
        """Upload images to ImageBox."""
        return await image_box_upload(
            filepaths=filepaths,
            title=title,
            thumb_width=thumb_width,
            square_thumbs=square_thumbs,
            adult=adult,
            comments_enabled=comments_enabled,
            batch_size=batch_size,
            progress_callback=progress_callback,
        )
