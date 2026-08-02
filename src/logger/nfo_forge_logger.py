from datetime import datetime
import json
import logging
from logging import StreamHandler
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import sys
from typing import Any, TextIO

import shortuuid

from src.backend.utils.working_dir import RUNTIME_DIR
from src.enums.logging_settings import DebugDataType, LogLevel, LogSource
from src.exceptions import DebugDumpError
from src.utils.secret_redaction import scrub_secrets
from src.version import __version__, program_name

_LOG_FILENAME_PATTERN = re.compile(
    r"^nfoforge_(?P<timestamp>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})_[^.]+\.log$"
)
_LOG_TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"


class Logger:
    LOG_SOURCE = LogSource
    LOG_LEVEL = LogLevel
    DUMP_TYPE = DebugDataType

    def __init__(
        self,
        log_file: Path,
        log_level: LogLevel = LogLevel.DEBUG,
        to_console: bool = False,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(log_level.value)
        self.log_file = log_file
        self.log_level = log_level
        self.file_handler: RotatingFileHandler | None = None
        self.console_handler: StreamHandler[TextIO] | None = None
        self.to_console = to_console
        self.dumps = log_file.parent / "dumps"

        log_file.parent.mkdir(parents=True, exist_ok=True)
        self.dumps.mkdir(parents=True, exist_ok=True)

    def _initialize_file_handler(self) -> None:
        # if none we can assume we're initiating this for the first time
        log_program_info = True if not self.file_handler else False

        # file handler
        if self.file_handler is None:
            self.file_handler = RotatingFileHandler(
                self.log_file,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            self.file_handler.setFormatter(
                logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            )
            self.logger.addHandler(self.file_handler)

        # console handler (print to console)
        if self.console_handler is None and self.to_console:
            self.console_handler = logging.StreamHandler(sys.stdout)
            self.console_handler.setFormatter(
                logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            )
            self.logger.addHandler(self.console_handler)

        # log initial program info
        if log_program_info:
            self.info(self.LOG_SOURCE.FE, f"{program_name} v{__version__}")

    def _log(self, level: int, source: LogSource, message: object) -> None:
        if self.logger.level <= level:
            self._initialize_file_handler()
            safe_message = scrub_secrets(str(message).strip())
            self.logger.log(level, f"{source.value}: {safe_message}")

    def debug(self, source: LogSource, message: object) -> None:
        self._log(logging.DEBUG, source, message)

    def info(self, source: LogSource, message: object) -> None:
        self._log(logging.INFO, source, message)

    def warning(self, source: LogSource, message: object) -> None:
        self._log(logging.WARNING, source, message)

    def error(self, source: LogSource, message: object) -> None:
        self._log(logging.ERROR, source, message)

    def critical(self, source: LogSource, message: object) -> None:
        self._log(logging.CRITICAL, source, message)

    def set_log_level(self, log_level: LogLevel) -> None:
        self.logger.setLevel(log_level.value)

    def clean_up_logs(self, max_logs: int) -> None:
        """Remove old per-run logs without touching diagnostic log files.

        Session logs are named ``nfoforge_<timestamp>_<id>.log``.  The crash
        dump is intentionally stored beside them as ``crash.log`` and must not
        be included in this retention count.  Invalid or incomplete filenames
        are ignored rather than preventing startup from completing.
        """
        if max_logs < 1:
            # Keep the active log alive even if an old/hand-edited config has a
            # zero retention value. The settings UI already requires at least
            # ten files, but this also protects legacy configurations.
            return

        log_files: list[tuple[datetime, Path]] = []
        for candidate in self.log_file.parent.glob("nfoforge_*.log"):
            timestamp = self._parse_log_timestamp(candidate)
            if timestamp is not None:
                log_files.append((timestamp, candidate))

        log_files.sort(key=lambda item: (item[0], item[1].name))
        files_to_delete = log_files[:-max_logs]

        for _, log_file in files_to_delete:
            try:
                log_file.unlink()
            except OSError as error:
                # Cleanup is best-effort: another NfoForge instance or an
                # antivirus scanner may briefly hold a file open on Windows.
                self.warning(
                    self.LOG_SOURCE.FE,
                    f"Could not remove old log file {log_file}: {error}",
                )

    @staticmethod
    def _parse_log_timestamp(log_file: Path) -> datetime | None:
        match = _LOG_FILENAME_PATTERN.fullmatch(log_file.name)
        if match is None:
            return None

        try:
            return datetime.strptime(match.group("timestamp"), _LOG_TIMESTAMP_FORMAT)
        except ValueError:
            return None

    def dump_debug_data(
        self, file_output: Path, debug_type: DebugDataType, data: str | dict[str, Any]
    ) -> None:
        self._check_dump_type(debug_type, data)
        file_output = self._generate_dump_file_path(Path(file_output), debug_type)
        try:
            if debug_type == self.DUMP_TYPE.JSON and isinstance(data, dict):
                self._dump_debug_data_json(file_output, data)
            if debug_type == self.DUMP_TYPE.TEXT and isinstance(data, str):
                self._dump_debug_data_str(file_output, data)
        except Exception as e:
            raise DebugDumpError(f"Error dumping debug data: {str(e)}") from e

    def _generate_dump_file_path(
        self, file_output: Path, debug_type: DebugDataType
    ) -> Path:
        file_name = (
            f"{file_output.stem}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
            f"_{shortuuid.uuid()[:7]}{debug_type.value}"
        )
        return self.dumps / file_name

    def _check_dump_type(
        self, debug_type: DebugDataType, data: str | dict[str, Any]
    ) -> None:
        if debug_type == self.DUMP_TYPE.JSON and not isinstance(data, dict):
            raise DebugDumpError(
                "Invalid data type for JSON debug dump: expected 'dict'"
            )

        if debug_type == self.DUMP_TYPE.TEXT and not isinstance(data, str):
            raise DebugDumpError(
                "Invalid data type for text debug dump: expected 'str'"
            )

    def _dump_debug_data_json(
        self, file_output: Path, data: dict[str, Any] | None
    ) -> None:
        if data:
            with open(file_output, "w") as json_file:
                self.debug(
                    self.LOG_SOURCE.BE,
                    f"Dumping debug data (json) for {file_output.name}",
                )
                json_file.write(json.dumps(data, indent=2))

    def _dump_debug_data_str(self, file_output: Path, data: str | None) -> None:
        if data:
            with open(file_output, "w") as text_file:
                self.debug(
                    self.LOG_SOURCE.BE,
                    f"Dumping debug data (text) for {file_output.name}",
                )
                text_file.write(data)


_date_time_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
_short_uuid = shortuuid.uuid()[:7]
_log_path = RUNTIME_DIR / "logs" / f"nfoforge_{_date_time_str}_{_short_uuid}.log"
debug_env = str(os.environ.get("LOG_LEVEL", "")).lower()
LOG = Logger(
    _log_path,
    to_console="debug" in sys.executable.lower() or debug_env == "debug",
)
