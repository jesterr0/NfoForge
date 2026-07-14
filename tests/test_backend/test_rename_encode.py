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
