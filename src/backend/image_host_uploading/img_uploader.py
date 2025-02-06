import asyncio
import uuid
from collections.abc import Sequence, Callable
from pathlib import Path

from src.packages.custom_types import ImageUploadData
from src.backend.image_host_uploading.base_image_host import BaseImageHostUploader


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
        self._jobs = {}  # stores (uploader, filepaths)
        self._progress_trackers = {}
        self._uploaders = {}

    def register_uploader(
        self, host_name: str, uploader: BaseImageHostUploader
    ) -> None:
        """Register a specific image host uploader."""
        self._uploaders[host_name] = uploader

    def add_job(
        self, host_name: str, filepaths: Sequence[Path], *args, **kwargs
    ) -> str:
        """Queue an upload job for a specific image host."""
        if host_name not in self._uploaders:
            raise ValueError(f"No uploader registered for host: {host_name}")

        job_id = str(uuid.uuid4())
        total_files = len(filepaths)

        self._progress_trackers[job_id] = {
            "total": total_files,
            "remaining": total_files,
        }

        # store uploader + filepaths (delayed execution)
        self._jobs[job_id] = (self._uploaders[host_name], filepaths, args, kwargs)

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
        results = {}

        tasks = [
            self._run_job(job_id, uploader, filepaths, args, kwargs, results)
            for job_id, (uploader, filepaths, args, kwargs) in self._jobs.items()
        ]

        await asyncio.gather(*tasks)
        return results

    async def _run_job(
        self, job_id: str, uploader, filepaths, args, kwargs, results: dict
    ):
        """Runs a single job and stores its results."""

        async def progress_callback(_idx: int) -> None:
            await self.upload_progress(job_id)

        upload_results = await uploader.upload(
            filepaths, progress_callback=progress_callback, *args, **kwargs
        )
        results[job_id] = upload_results
