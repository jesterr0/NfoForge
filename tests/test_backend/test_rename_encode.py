import errno
from pathlib import Path

import pytest
from tenacity.wait import wait_none

from src.backend import rename_files
from src.backend.rename_files import RenameExecutor, RenamePlan


@pytest.fixture(autouse=True)
def _disable_rename_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rename_files, "wait_exponential", lambda **_kwargs: wait_none())


def test_execute_rejects_colliding_targets_without_mutation(tmp_path: Path) -> None:
    first = tmp_path / "a.mkv"
    first.write_text("a")
    second = tmp_path / "b.mkv"
    second.write_text("b")
    target = tmp_path / "Show.S01E01.mkv"

    result = RenameExecutor.execute(
        RenamePlan.build({first: target, second: target}, input_path=None)
    )

    assert result.success is False
    assert "same destination" in (result.message or "")
    assert first.exists() and second.exists()


def test_execute_rejects_existing_folder_without_mutation(tmp_path: Path) -> None:
    source_directory = tmp_path / "old"
    source_directory.mkdir()
    source = source_directory / "old.mkv"
    source.write_text("data")
    target_directory = tmp_path / "new"
    target_directory.mkdir()
    target = target_directory / "new.mkv"

    result = RenameExecutor.execute(
        RenamePlan.build({source: target}, input_path=source_directory)
    )

    assert result.success is False
    assert "Destination already exists" in (result.message or "")
    assert source.exists()
    assert not target.exists()


def test_execute_renames_parent_directory_and_file(tmp_path: Path) -> None:
    source_directory = tmp_path / "Show Season 1"
    source_directory.mkdir()
    source = source_directory / "raw_episode.mkv"
    source.write_text("data")
    target_directory = tmp_path / "Show.S01"
    target = target_directory / "Show.S01E01.mkv"

    result = RenameExecutor.execute(
        RenamePlan.build({source: target}, input_path=source_directory)
    )

    assert result.success is True
    assert not source_directory.exists()
    assert target.is_file()
    assert result.path_mapping == {source: target}
    assert result.updated_input_path == target_directory


def test_execute_records_file_moved_by_parent_only(tmp_path: Path) -> None:
    source_directory = tmp_path / "Show Season 1"
    source_directory.mkdir()
    source = source_directory / "Show.S01E01.mkv"
    source.write_text("data")
    target_directory = tmp_path / "Show.S01"
    target = target_directory / source.name

    result = RenameExecutor.execute(
        RenamePlan.build({source: target}, input_path=source_directory)
    )

    assert result.success is True
    assert result.path_mapping == {source: target}
    assert result.updated_input_path == target_directory


def test_transient_permission_error_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "old.mkv"
    source.write_text("data")
    target = tmp_path / "new.mkv"
    original_rename = Path.rename
    attempts = 0

    def flaky_rename(path: Path, rename_target: Path) -> Path:
        nonlocal attempts
        if path == source and rename_target == target:
            attempts += 1
            if attempts < 3:
                raise PermissionError(errno.EACCES, "temporarily locked", str(path))
        return original_rename(path, rename_target)

    monkeypatch.setattr(Path, "rename", flaky_rename)

    result = RenameExecutor.execute(
        RenamePlan.build({source: target}, input_path=source)
    )

    assert result.success is True
    assert attempts == 3
    assert target.is_file()


def test_folder_failure_rolls_back_completed_file_renames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_directory = tmp_path / "old"
    source_directory.mkdir()
    first = source_directory / "one.mkv"
    second = source_directory / "two.mkv"
    first.write_text("1")
    second.write_text("2")
    target_directory = tmp_path / "new"
    targets = {
        first: target_directory / "Show.S01E01.mkv",
        second: target_directory / "Show.S01E02.mkv",
    }
    original_rename = Path.rename

    def fail_folder_rename(path: Path, target: Path) -> Path:
        if path == source_directory and target == target_directory:
            raise PermissionError(errno.EACCES, "folder locked", str(path))
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_folder_rename)

    result = RenameExecutor.execute(
        RenamePlan.build(targets, input_path=source_directory)
    )

    assert result.success is False
    assert result.rollback_complete is True
    assert result.path_mapping == {}
    assert first.is_file() and second.is_file()
    assert not (source_directory / "Show.S01E01.mkv").exists()
    assert not target_directory.exists()


def test_incomplete_rollback_reports_actual_surviving_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "one.mkv"
    second = tmp_path / "two.mkv"
    first.write_text("1")
    second.write_text("2")
    first_target = tmp_path / "Show.S01E01.mkv"
    second_target = tmp_path / "Show.S01E02.mkv"
    original_rename = Path.rename

    def fail_second_and_rollback(path: Path, target: Path) -> Path:
        if path == second and target == second_target:
            raise PermissionError(errno.EACCES, "second locked", str(path))
        if path == first_target and target == first:
            raise PermissionError(errno.EACCES, "rollback locked", str(path))
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_second_and_rollback)

    result = RenameExecutor.execute(
        RenamePlan.build(
            {first: first_target, second: second_target},
            input_path=tmp_path,
        )
    )

    assert result.success is False
    assert result.rollback_complete is False
    assert result.path_mapping == {first: first_target}
    assert first_target.is_file()
    assert second.is_file()


def test_case_only_rename_uses_an_in_place_temporary_hop(tmp_path: Path) -> None:
    source = tmp_path / "movie.mkv"
    source.write_text("data")
    target = tmp_path / "MOVIE.mkv"

    result = RenameExecutor.execute(
        RenamePlan.build({source: target}, input_path=source)
    )

    assert result.success is True
    assert target.is_file()
    assert result.updated_input_path == target


def test_execute_resequences_files_with_occupied_targets(tmp_path: Path) -> None:
    first = tmp_path / "Show.S01E01.mkv"
    second = tmp_path / "Show.S01E02.mkv"
    third = tmp_path / "Show.S01E03.mkv"
    first.write_text("episode one")
    second.write_text("episode two")

    result = RenameExecutor.execute(
        RenamePlan.build(
            {first: second, second: third},
            input_path=tmp_path,
        )
    )

    assert result.success is True
    assert result.path_mapping == {first: second, second: third}
    assert not first.exists()
    assert second.read_text() == "episode one"
    assert third.read_text() == "episode two"


def test_execute_resequences_files_while_renaming_parent_folder(
    tmp_path: Path,
) -> None:
    source_directory = tmp_path / "Show Season 1"
    source_directory.mkdir()
    target_directory = tmp_path / "Show.S01"
    first = source_directory / "Show.S01E01.mkv"
    second = source_directory / "Show.S01E02.mkv"
    first.write_text("episode one")
    second.write_text("episode two")
    second_target = target_directory / second.name
    third_target = target_directory / "Show.S01E03.mkv"

    result = RenameExecutor.execute(
        RenamePlan.build(
            {first: second_target, second: third_target},
            input_path=source_directory,
        )
    )

    assert result.success is True
    assert result.path_mapping == {first: second_target, second: third_target}
    assert result.updated_input_path == target_directory
    assert not source_directory.exists()
    assert second_target.read_text() == "episode one"
    assert third_target.read_text() == "episode two"


def test_execute_swaps_files_with_occupied_targets(tmp_path: Path) -> None:
    first = tmp_path / "Show.S01E01.mkv"
    second = tmp_path / "Show.S01E02.mkv"
    first.write_text("episode one")
    second.write_text("episode two")

    result = RenameExecutor.execute(
        RenamePlan.build({first: second, second: first}, input_path=tmp_path)
    )

    assert result.success is True
    assert result.path_mapping == {first: second, second: first}
    assert first.read_text() == "episode two"
    assert second.read_text() == "episode one"


def test_execute_rejects_existing_file_outside_plan(tmp_path: Path) -> None:
    source = tmp_path / "Show.S01E01.mkv"
    target = tmp_path / "Show.S01E02.mkv"
    source.write_text("episode one")
    target.write_text("unrelated file")

    result = RenameExecutor.execute(
        RenamePlan.build({source: target}, input_path=tmp_path)
    )

    assert result.success is False
    assert "Destination already exists" in (result.message or "")
    assert source.read_text() == "episode one"
    assert target.read_text() == "unrelated file"


def test_colliding_rename_failure_rolls_back_temporary_hops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "Show.S01E01.mkv"
    second = tmp_path / "Show.S01E02.mkv"
    third = tmp_path / "Show.S01E03.mkv"
    first.write_text("episode one")
    second.write_text("episode two")
    original_rename = Path.rename

    def fail_final_temporary_hop(path: Path, target: Path) -> Path:
        if ".nfoforge-rename-" in path.name and target == third:
            raise PermissionError(errno.EACCES, "temporarily locked", str(path))
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_final_temporary_hop)

    result = RenameExecutor.execute(
        RenamePlan.build(
            {first: second, second: third},
            input_path=tmp_path,
        )
    )

    assert result.success is False
    assert result.rollback_complete is True
    assert result.path_mapping == {}
    assert first.read_text() == "episode one"
    assert second.read_text() == "episode two"
    assert not third.exists()
    assert not list(tmp_path.glob("*.nfoforge-rename-*.tmp"))


def test_single_file_rename_rejects_destination_outside_source_folder(
    tmp_path: Path,
) -> None:
    source = tmp_path / "movie.mkv"
    source.write_text("data")
    destination_directory = tmp_path / "outside"
    destination_directory.mkdir()
    target = destination_directory / "renamed.mkv"

    result = RenameExecutor.execute(
        RenamePlan(
            file_targets={source: target}, directory_targets={}, input_path=source
        )
    )

    assert result.success is False
    assert "stay in the source folder" in (result.message or "")
    assert source.is_file()
    assert not target.exists()
