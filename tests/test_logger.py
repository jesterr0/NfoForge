from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from src.enums.logging_settings import LogSource
from src.logger.nfo_forge_logger import Logger


def _session_log(log_dir: Path, timestamp: str, suffix: str) -> Path:
    path = log_dir / f"nfoforge_{timestamp}_{suffix}.log"
    path.touch()
    return path


def test_clean_up_logs_ignores_diagnostic_and_invalid_files(tmp_path: Path) -> None:
    logger = Logger(tmp_path / "nfoforge_2026-07-29_12-00-00_current.log")
    oldest = _session_log(tmp_path, "2026-07-27_12-00-00", "old")
    newest = _session_log(tmp_path, "2026-07-29_12-00-00", "new")
    crash_log = tmp_path / "crash.log"
    crash_log.write_text("crash details", encoding="utf-8")
    invalid_log = tmp_path / "nfoforge_not-a-timestamp.log"
    invalid_log.write_text("keep this file", encoding="utf-8")

    logger.clean_up_logs(max_logs=1)

    assert not oldest.exists()
    assert newest.exists()
    assert crash_log.exists()
    assert invalid_log.exists()


def test_clean_up_logs_keeps_at_least_one_session_log_for_zero_retention(
    tmp_path: Path,
) -> None:
    current = _session_log(tmp_path, "2026-07-29_12-00-00", "current")
    logger = Logger(current)

    logger.clean_up_logs(max_logs=0)

    assert current.exists()


def test_parse_log_timestamp_rejects_unrelated_names(tmp_path: Path) -> None:
    valid = tmp_path / "nfoforge_2026-07-29_12-00-00_abc123.log"
    invalid = tmp_path / "crash.log"
    malformed = tmp_path / "nfoforge_2026-99-99_12-00-00_abc123.log"

    assert Logger._parse_log_timestamp(valid) == datetime(2026, 7, 29, 12, 0, 0)
    assert Logger._parse_log_timestamp(invalid) is None
    assert Logger._parse_log_timestamp(malformed) is None


def test_logger_redacts_credentials_before_writing(tmp_path: Path, monkeypatch) -> None:
    logger = Logger(tmp_path / "nfoforge_2026-07-29_12-00-00_current.log")
    log_call = MagicMock()
    monkeypatch.setattr(logger, "_initialize_file_handler", lambda: None)
    monkeypatch.setattr(logger.logger, "log", log_call)

    logger.error(
        LogSource.BE,
        "Request failed: /api/upload/APISECRET?api_token=QUERYSECRET",
    )

    message = log_call.call_args.args[1]
    assert "APISECRET" not in message
    assert "QUERYSECRET" not in message
    assert "/api/upload/[redacted]" in message
    assert "api_token=[redacted]" in message
