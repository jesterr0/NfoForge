from pathlib import Path

import pytest

from src.backend.rename_encode import RenameEncodeBackEnd


def test_execute_renames_rejects_colliding_targets(tmp_path: Path) -> None:
    a = tmp_path / "a.mkv"
    a.write_text("a")
    b = tmp_path / "b.mkv"
    b.write_text("b")
    target = tmp_path / "Show.S01E01.mkv"
    rename_map = {a: target, b: target}
    with pytest.raises(FileExistsError):
        RenameEncodeBackEnd.execute_renames(rename_map, input_path=None)
    # neither source was renamed
    assert a.exists() and b.exists()


def test_execute_renames_renames_parent_directory_and_file(tmp_path: Path) -> None:
    # normal, non-colliding rename that also renames the file's parent
    # directory (phase 1) before the file itself is moved into place
    # (phase 2), proving the directory-rename phase completes correctly.
    src_dir = tmp_path / "Show Season 1"
    src_dir.mkdir()
    src_file = src_dir / "raw_episode.mkv"
    src_file.write_text("data")

    trg_dir = tmp_path / "Show.S01"
    target_file = trg_dir / "Show.S01E01.mkv"
    rename_map = {src_file: target_file}

    rename_mapping, updated_input_path = RenameEncodeBackEnd.execute_renames(
        rename_map, input_path=src_dir
    )

    assert not src_dir.exists()
    assert trg_dir.exists()
    assert target_file.exists()
    assert rename_mapping == {src_file: target_file}
    assert updated_input_path == trg_dir
