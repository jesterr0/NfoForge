import asyncio
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import SignalInstance
from pymediainfo import MediaInfo

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
    ) -> dict[Path, MediaInfo]:
        """Async version with controlled concurrency to avoid overwhelming the disk."""
        self._completed_files = 0
        self._semaphore = asyncio.Semaphore(max_concurrent)

        total = len(files)
        media_info_data = {}

        async def process_file(file_path: Path) -> tuple[Path, MediaInfo | None]:
            async with self._semaphore:  # pyright: ignore [reportOptionalContextManager]
                # run MediaInfo.parse in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                media_info = await loop.run_in_executor(
                    None, self.get_media_info, file_path
                )

                self._completed_files += 1
                progress = int((self._completed_files / total) * 100)
                self.progress_signal.emit(progress, self._completed_files, total)

                return file_path, media_info

        # create tasks for all files
        tasks = [process_file(file_path) for file_path in files]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # process results
        for result in results:
            # skip failed files
            if isinstance(result, BaseException):
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"Failed to process file: {type(result).__name__}: {str(result)}",
                )
                continue
            try:
                file_path, media_info = result
                if media_info:
                    media_info_data[file_path] = media_info
                else:
                    LOG.warning(
                        LOG.LOG_SOURCE.BE,
                        f"MediaInfo parsing returned None for file: {file_path}",
                    )
            # skip malformed results
            except (TypeError, ValueError) as e:
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"Malformed result when processing file: {type(e).__name__}: {str(e)} - Result: {result}",
                )
                continue

        return media_info_data

    def get_media_info_files(self, files: Sequence[Path]) -> dict[Path, MediaInfo]:
        """Sync wrapper that runs the async version."""
        # we're in QThread context so we're safe to create a new async loop
        return asyncio.run(self.get_media_info_files_async(files))

    @staticmethod
    def get_media_info(file_input: Path) -> MediaInfo | None:
        data = MediaInfo.parse(file_input)
        return data if isinstance(data, MediaInfo) else None
