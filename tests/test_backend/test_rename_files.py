from pathlib import Path

from src.backend.rename_files import RenameExecutor, RenamePlan, _is_case_only_change


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
    assert "too long" in result.message.lower()
    # The misleading "moved or renamed outside NfoForge" text must not appear.
    assert "outside NfoForge" not in result.message


def test_case_only_change_is_detected_independently_of_platform() -> None:
    # `os.path.normcase` is identity on POSIX, so it cannot be the basis for
    # this check on case-insensitive macOS volumes.
    assert _is_case_only_change(Path("/m/movie.mkv"), Path("/m/MOVIE.mkv")) is True
    assert _is_case_only_change(Path("/m/movie.mkv"), Path("/m/other.mkv")) is False
