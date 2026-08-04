from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from torf import Torrent

from src.backend.torrents import torrent as torrent_module
from src.backend.torrents.torrent import (
    INDEX_SIDECAR_GLOBS,
    _validate_torrent_contents,
    generate_torrent,
    mkbrr_generate_torrent,
)
from src.payloads.trackers import TrackerInfo


def _release_with_indexes(tmp_path: Path) -> tuple[Path, Path]:
    release = tmp_path / "Release"
    release.mkdir()
    media = release / "Movie.mkv"
    media.write_bytes(b"media")
    (release / "Movie.lwi").write_bytes(b"lsmash index")
    (release / "Movie.ffindex").write_bytes(b"ffms2 index")
    return release, media


def test_torf_excludes_index_sidecars_without_removing_them(tmp_path: Path) -> None:
    release, _ = _release_with_indexes(tmp_path)
    tracker_info = TrackerInfo(announce_url="https://tracker.invalid/announce")

    torrent = generate_torrent(
        tracker_info=tracker_info,
        path=release,
        max_piece_size=None,
        cb=lambda *_args: None,
    )

    suffixes = {Path(str(file)).suffix.casefold() for file in torrent.files}
    assert ".lwi" not in suffixes
    assert ".ffindex" not in suffixes
    assert (release / "Movie.lwi").is_file()
    assert (release / "Movie.ffindex").is_file()


def test_torrent_content_validation_rejects_index_sidecars(tmp_path: Path) -> None:
    release, _ = _release_with_indexes(tmp_path)
    torrent = Torrent(path=release)
    torrent.generate()

    with pytest.raises(ValueError, match="excluded index sidecar"):
        _validate_torrent_contents(torrent)


def test_mkbrr_command_excludes_index_sidecars_and_validates_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, media = _release_with_indexes(tmp_path)
    output_path = tmp_path / "output.torrent"
    expected = Torrent(path=media)
    expected.generate()
    expected.write(output_path)
    captured_command: list[str] = []

    process = MagicMock()
    process.__enter__.return_value = process
    process.__exit__.return_value = False
    process.stdout = StringIO("Wrote torrent\n")
    process.returncode = 0

    def fake_popen(command: list[str], **_kwargs: Any) -> MagicMock:
        captured_command.extend(command)
        return process

    monkeypatch.setattr(torrent_module.subprocess, "Popen", fake_popen)

    result = mkbrr_generate_torrent(
        mkbrr_path=tmp_path / "mkbrr.exe",
        tracker_info=TrackerInfo(announce_url="https://tracker.invalid/announce"),
        path=release,
        output_path=output_path,
        max_piece_size=None,
        cb=lambda _progress: None,
    )

    assert result is not None
    exclude_values = [
        captured_command[index + 1]
        for index, value in enumerate(captured_command)
        if value == "--exclude"
    ]
    assert tuple(exclude_values) == INDEX_SIDECAR_GLOBS
