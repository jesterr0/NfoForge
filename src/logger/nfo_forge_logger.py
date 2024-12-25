import logging
import json
import shortuuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.enums.logging_settings import LogLevel, LogSource, DebugDataType
from src.exceptions import DebugDumpError
from src.backend.utils.working_dir import RUNTIME_DIR
from src.version import program_name, __version__


class Logger:
    LOG_SOURCE = LogSource
    LOG_LEVEL = LogLevel
    DUMP_TYPE = DebugDataType

    def __init__(
        self,
        log_file: Path,
        log_level: LogLevel = LogLevel.INFO,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(log_level.value)
        self.log_file = log_file
        self.log_level = log_level
        self.file_handler = None
        self.dumps = log_file.parent / "dumps"

        log_file.parent.mkdir(parents=True, exist_ok=True)
        self.dumps.mkdir(parents=True, exist_ok=True)

    def _initialize_file_handler(self) -> None:
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
            self.info(self.LOG_SOURCE.FE, f"{program_name} v{__version__}")

    def debug(self, source: LogSource, message: str) -> None:
        if self.logger.level <= logging.DEBUG:
            self._initialize_file_handler()
            self.logger.debug(f"{source.value}: {str(message).strip()}")

    def info(self, source: LogSource, message: str) -> None:
        if self.logger.level <= logging.INFO:
            self._initialize_file_handler()
            self.logger.info(f"{source.value}: {str(message).strip()}")

    def warning(self, source: LogSource, message: str) -> None:
        if self.logger.level <= logging.WARNING:
            self._initialize_file_handler()
            self.logger.warning(f"{source.value}: {str(message).strip()}")

    def error(self, source: LogSource, message: str) -> None:
        if self.logger.level <= logging.ERROR:
            self._initialize_file_handler()
            self.logger.error(f"{source.value}: {str(message).strip()}")

    def critical(self, source: LogSource, message: str) -> None:
        if self.logger.level <= logging.CRITICAL:
            self._initialize_file_handler()
            self.logger.critical(f"{source.value}: {str(message).strip()}")

    def set_log_level(self, log_level: LogLevel) -> None:
        self.logger.setLevel(log_level.value)

    def clean_up_logs(self, max_logs: int) -> None:
        log_files = list(self.log_file.parent.glob("*.log"))
        total_files = len(log_files)

        # sort log files by extracting the timestamp part of the filename
        log_files.sort(
            key=lambda f: datetime.strptime(
                f.name.split("_")[1] + "_" + f.name.split("_")[2], "%Y-%m-%d_%H-%M-%S"
            )
        )

        if total_files > max_logs:
            files_to_delete = log_files[: total_files - max_logs]

            for del_file in files_to_delete:
                del_file.unlink()

    def dump_debug_data(
        self, file_output: Path, debug_type: DebugDataType, data: str | dict
    ) -> None:
        self._check_dump_type(debug_type, data)
        file_output = self._generate_dump_file_path(Path(file_output), debug_type)
        try:
            if debug_type == self.DUMP_TYPE.JSON and isinstance(data, dict):
                self._dump_debug_data_json(file_output, data)
            if debug_type == self.DUMP_TYPE.TEXT and isinstance(data, str):
                self._dump_debug_data_str(file_output, data)
        except Exception as e:
            raise DebugDumpError(f"Error dumping debug data: {str(e)}")

    def _generate_dump_file_path(
        self, file_output: Path, debug_type: DebugDataType
    ) -> Path:
        file_name = (
            f"{file_output.stem}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
            f"_{shortuuid.uuid()[:7]}{debug_type.value}"
        )
        return self.dumps / file_name

    def _check_dump_type(self, debug_type: DebugDataType, data: str | dict) -> None:
        if debug_type == self.DUMP_TYPE.JSON and not isinstance(data, dict):
            raise DebugDumpError(
                "Invalid data type for JSON debug dump: expected 'dict'"
            )

        if debug_type == self.DUMP_TYPE.TEXT and not isinstance(data, str):
            raise DebugDumpError(
                "Invalid data type for text debug dump: expected 'str'"
            )

    def _dump_debug_data_json(self, file_output: Path, data: dict | None) -> None:
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
LOG = Logger(_log_path)
