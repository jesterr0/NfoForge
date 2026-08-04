from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

from PySide6.QtCore import SignalInstance
import pytest

from src.backend.media_input import MediaInputBackEnd


def _backend() -> MediaInputBackEnd:
    return MediaInputBackEnd(cast(SignalInstance, MagicMock()))


def test_a_failing_file_is_reported_with_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = tmp_path / "good.mkv"
    bad = tmp_path / "bad.mkv"
    good.write_bytes(b"x")
    bad.write_bytes(b"x")

    backend = _backend()

    def parse(file_input: Path) -> object:
        if file_input.name == "bad.mkv":
            raise OSError("unreadable stream")
        return object()  # stands in for a MediaInfo

    # `get_media_info` is a `@staticmethod` and the instance uses `__slots__`,
    # so it must be patched on the class (wrapped back in `staticmethod`) --
    # patching the instance directly raises `AttributeError` since there is
    # no per-instance `__dict__` to shadow it in.
    monkeypatch.setattr(MediaInputBackEnd, "get_media_info", staticmethod(parse))

    parsed, failures = backend.get_media_info_files([good, bad])

    assert good in parsed
    assert bad not in parsed
    assert bad in failures
    assert "unreadable stream" in failures[bad]


def test_a_file_parsing_to_none_is_reported_as_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "empty.mkv"
    media.write_bytes(b"x")
    backend = _backend()
    monkeypatch.setattr(
        MediaInputBackEnd, "get_media_info", staticmethod(lambda _path: None)
    )

    parsed, failures = backend.get_media_info_files([media])

    assert parsed == {}
    assert media in failures


def test_all_files_succeeding_reports_no_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "good.mkv"
    media.write_bytes(b"x")
    backend = _backend()
    monkeypatch.setattr(
        MediaInputBackEnd, "get_media_info", staticmethod(lambda _path: object())
    )

    parsed, failures = backend.get_media_info_files([media])

    assert media in parsed
    assert failures == {}
