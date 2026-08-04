import asyncio
from collections.abc import Sequence
from pathlib import Path

from pymediainfo import MediaInfo
from PySide6.QtCore import SignalInstance

from src.logger.nfo_forge_logger import LOG


class MediaInputBackEnd:
    __slots__ = (
        "progress_signal",
        "_completed_files",
        "_semaphore",
    )

    def __init__(self, progress_signal: SignalInstance) -> None:
        self.progress_signal = progress_signal

        self._completed_files = 0
        self._semaphore: asyncio.Semaphore | None = None

    async def get_media_info_files_async(
        self, files: Sequence[Path], max_concurrent: int = 4
    ) -> tuple[dict[Path, MediaInfo], dict[Path, str]]:
        """Async version with controlled concurrency to avoid overwhelming the disk.

        Returns a tuple of ``(parsed, failures)`` where ``parsed`` maps each
        successfully processed file to its ``MediaInfo`` and ``failures`` maps
        each file that could not be processed to a human-readable reason.
        """
        self._completed_files = 0
        semaphore = asyncio.Semaphore(max_concurrent)
        self._semaphore = semaphore

        total = len(files)
        media_info_data: dict[Path, MediaInfo] = {}
        failures: dict[Path, str] = {}

        async def process_file(file_path: Path) -> None:
            async with semaphore:
                loop = asyncio.get_event_loop()
                try:
                    media_info = await loop.run_in_executor(
                        None, self.get_media_info, file_path
                    )
                except Exception as error:
                    # Caught here rather than at the gather, because that is the
                    # last point where the failure can still be attributed to a
                    # file -- `gather(return_exceptions=True)` hands back a bare
                    # exception with no way to tell which task raised it.
                    failures[file_path] = f"{type(error).__name__}: {error}"
                    media_info = None

                if media_info is not None:
                    media_info_data[file_path] = media_info
                elif file_path not in failures:
                    failures[file_path] = "MediaInfo returned no data for this file"

                self._completed_files += 1
                progress = int((self._completed_files / total) * 100)
                self.progress_signal.emit(progress, self._completed_files, total)

        await asyncio.gather(*(process_file(file_path) for file_path in files))

        for file_path, reason in failures.items():
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Failed to read MediaInfo for {file_path}: {reason}",
            )

        return media_info_data, failures

    def get_media_info_files(
        self, files: Sequence[Path]
    ) -> tuple[dict[Path, MediaInfo], dict[Path, str]]:
        """Sync wrapper that runs the async version."""
        # we're in QThread context so we're safe to create a new async loop
        return asyncio.run(self.get_media_info_files_async(files))

    @staticmethod
    def get_media_info(file_input: Path) -> MediaInfo | None:
        data = MediaInfo.parse(file_input, legacy_stream_display=True)
        return data if isinstance(data, MediaInfo) else None
