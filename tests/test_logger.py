from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from nfoforge.config.paths import default_paths
from nfoforge.enums.logging_settings import LogSource
from nfoforge.logger.nfo_forge_logger import Logger, default_log_file


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


def test_this_run_logs_into_the_per_user_data_directory() -> None:
    """Logs are user state, so they belong with the rest of it.

    They used to live inside the installation, which meant replacing a release
    discarded the logs describing whatever went wrong with the one before it --
    exactly when someone wants them.
    """
    assert default_log_file().parent == default_paths().logs


def test_a_logger_whose_directory_cannot_be_created_still_works(
    tmp_path: Path,
) -> None:
    """Logging is the thing that reports failures, so it must not be one.

    The log directory is created while this module is imported, before any
    handler or dialog exists to report a problem. An exception there does not
    produce a logging error, it produces an application that will not start, and
    the one thing that could have explained why is the thing that failed.
    """
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("in the way", encoding="utf-8")

    logger = Logger(blocker / "logs" / "nfoforge.log")
    logger.info(LogSource.BE, "this must not raise")

    assert logger.file_logging is False


def test_a_logger_whose_file_cannot_be_opened_still_works(tmp_path: Path) -> None:
    """The directory existing is not the same as the file being writable.

    A name already taken by a directory, a file held open by something else, a
    quota refusal: the handler is built on first use, so this fails later than
    the directory does and needs its own guard.
    """
    occupied = tmp_path / "logs" / "nfoforge.log"
    occupied.mkdir(parents=True)

    logger = Logger(occupied)
    logger.info(LogSource.BE, "this must not raise either")

    assert logger.file_logging is False


def test_a_logger_with_a_usable_directory_logs_to_its_file(tmp_path: Path) -> None:
    """The guard must not be a quiet opt-out of logging altogether."""
    logger = Logger(tmp_path / "logs" / "nfoforge.log")
    logger.info(LogSource.BE, "recorded")

    assert logger.file_logging is True
    assert (tmp_path / "logs" / "nfoforge.log").read_text(encoding="utf-8").strip()
