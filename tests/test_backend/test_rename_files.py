import errno
from pathlib import Path

from src.backend.rename_files import (
    _MAX_NAME_LENGTH,
    RenameExecutor,
    RenamePlan,
    _is_case_only_change,
)


def test_non_oserror_failure_still_rolls_back(tmp_path, monkeypatch) -> None:
    # A ValueError escaping mid-plan must not leave the disk half-renamed with
    # the app still pointing at the old paths.
    source_a = tmp_path / "a.mkv"
    source_b = tmp_path / "b.mkv"
    source_a.write_bytes(b"a")
    source_b.write_bytes(b"b")

    plan = RenamePlan(
        input_path=tmp_path,
        file_targets={
            source_a: tmp_path / "a_new.mkv",
            source_b: tmp_path / "b_new.mkv",
        },
        directory_targets={},
    )

    call_count = 0
    real_rename = Path.rename

    def fail_on_second(self: Path, target: Path) -> Path:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise ValueError("not an OSError")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_on_second)
    result = RenameExecutor.execute(plan)

    assert result.success is False
    assert source_a.exists()
    assert source_b.exists()


def test_path_that_exceeds_the_limit_is_rejected_with_a_clear_message(
    tmp_path,
) -> None:
    long_name = "x" * 300 + ".mkv"
    source = tmp_path / "short.mkv"
    source.write_bytes(b"x")

    plan = RenamePlan.build({source: tmp_path / long_name}, source)
    result = RenameExecutor.execute(plan)

    assert result.success is False
    # Assert on the structure only `_preflight`'s proactive guard produces
    # (the measured byte length and the configured limit), not the bare
    # phrase "too long". On POSIX, the OS's own ENAMETOOLONG strerror is
    # literally "File name too long" -- with the fix reverted, the rename
    # instead fails reactively (via `_reject_existing_target`'s
    # `target.exists()` stat() call raising ENAMETOOLONG, caught by the
    # pre-existing `except (OSError, ValueError)` around `_preflight`), and
    # that OS message would satisfy a bare "too long" substring check too.
    expected_length = len(long_name.encode("utf-8"))
    assert f"{expected_length} bytes, limit {_MAX_NAME_LENGTH}" in result.message
    # The misleading "moved or renamed outside NfoForge" text must not appear.
    assert "outside NfoForge" not in result.message


def test_format_error_reports_path_too_long_for_enametoolong() -> None:
    # Direct coverage for Part B of the fix: an OSError carrying
    # errno.ENAMETOOLONG (what POSIX raises for an over-long path) must be
    # reported with guidance to shorten the template, not the generic
    # fallback message.
    error = OSError(errno.ENAMETOOLONG, "File name too long")
    message = RenameExecutor._format_error(error)
    assert "shorten the filename template" in message.lower()


def test_format_error_reports_path_too_long_for_windows_winerror() -> None:
    # Direct coverage for Part B's Windows path: WinError 3/206 carry no
    # POSIX errno, so this must be proven with a synthetic winerror rather
    # than relying on which OS runs the suite.
    class _FakeWindowsOSError(OSError):
        pass

    error = _FakeWindowsOSError("The filename or extension is too long")
    error.winerror = 206  # pyright: ignore[reportAttributeAccessIssue]
    message = RenameExecutor._format_error(error)
    assert "shorten the filename template" in message.lower()


def test_case_only_change_is_detected_independently_of_platform() -> None:
    # `os.path.normcase` is identity on POSIX, so it cannot be the basis for
    # this check on case-insensitive macOS volumes.
    assert _is_case_only_change(Path("/m/movie.mkv"), Path("/m/MOVIE.mkv")) is True
    assert _is_case_only_change(Path("/m/movie.mkv"), Path("/m/other.mkv")) is False
