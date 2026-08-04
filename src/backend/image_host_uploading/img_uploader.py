import asyncio
from collections.abc import Callable, Mapping
from dataclasses import replace
import uuid

from src.backend.image_host_uploading.base_image_host import (
    BaseImageHostUploader,
    ImageUploadRequest,
)
from src.exceptions import ImageUploadError
from src.packages.custom_types import ImageUploadData


def assert_all_images_uploaded(
    tracker: str, images: Mapping[int, ImageUploadData]
) -> None:
    """Raise if any requested upload produced no URL.

    PassThePopcorn's poster path already checks for this shape; the general
    path did not, so a partially failed batch reached the tracker looking
    like a complete set.
    """
    failed = sorted(index for index, item in images.items() if not item.url)
    if failed:
        raise ImageUploadError(
            f"{len(failed)} of {len(images)} image uploads failed for "
            f"{tracker} (positions: {', '.join(str(index) for index in failed)})"
        )


class ImageUploader:
    """Manages image uploads across multiple hosts with progress tracking."""

    def __init__(
        self,
        progress_signal: Callable[[str, int, int], None] | None = None,
        delete_job_as_completed: bool = False,
    ) -> None:
        self.progress_signal = progress_signal
        self.delete_job_as_completed = delete_job_as_completed
        self._lock = asyncio.Lock()
        self._jobs: dict[
            str,
            tuple[BaseImageHostUploader, ImageUploadRequest],
        ] = {}
        self._progress_trackers: dict[str, dict[str, int]] = {}
        self._uploaders: dict[str, BaseImageHostUploader] = {}

    def register_uploader(
        self, host_name: str, uploader: BaseImageHostUploader
    ) -> None:
        """Register a specific image host uploader."""
        self._uploaders[host_name] = uploader

    def add_job(
        self,
        host_name: str,
        request: ImageUploadRequest,
    ) -> str:
        """Queue an upload job for a specific image host."""
        if host_name not in self._uploaders:
            raise ValueError(f"No uploader registered for host: {host_name}")

        job_id = str(uuid.uuid4())
        total_files = len(request.filepaths)

        self._progress_trackers[job_id] = {
            "total": total_files,
            "remaining": total_files,
        }

        self._jobs[job_id] = (self._uploaders[host_name], request)

        return job_id

    async def upload_progress(self, job_id: str) -> None:
        """Updates progress for each job and emits a signal."""
        async with self._lock:
            if job_id not in self._progress_trackers:
                return

            tracker = self._progress_trackers[job_id]
            tracker["remaining"] -= 1
            total = tracker["total"]
            remaining = tracker["remaining"]

            individual_progress = int(((total - remaining) / total) * 100)

            # compute overall progress
            total_files_overall = sum(
                tr["total"] for tr in self._progress_trackers.values()
            )
            remaining_overall = sum(
                tr["remaining"] for tr in self._progress_trackers.values()
            )
            overall_progress = int(
                ((total_files_overall - remaining_overall) / total_files_overall) * 100
            )

            if self.progress_signal:
                self.progress_signal(job_id, individual_progress, overall_progress)

            if self.delete_job_as_completed and remaining == 0:
                del self._progress_trackers[job_id]

    async def start_jobs(self) -> dict[str, dict[int, ImageUploadData]]:
        """Starts all registered jobs and collects results."""
        results: dict[str, dict[int, ImageUploadData]] = {}

        tasks = [
            self._run_job(job_id, uploader, request, results)
            for job_id, (uploader, request) in self._jobs.items()
        ]

        await asyncio.gather(*tasks)
        return results

    async def _run_job(
        self,
        job_id: str,
        uploader: BaseImageHostUploader,
        request: ImageUploadRequest,
        results: dict[str, dict[int, ImageUploadData]],
    ) -> None:
        """Runs a single job and stores its results."""

        async def progress_callback(_idx: int) -> None:
            await self.upload_progress(job_id)

        upload_results = await uploader.upload(
            replace(request, progress_callback=progress_callback)
        )
        results[job_id] = upload_results
