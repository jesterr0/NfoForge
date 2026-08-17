"""Regression coverage for the shared disc-title heuristic.

``DISC_TITLE_REGEX`` (src/backend/trackers/utils.py) used to exist as four
independently-copied, case-sensitive patterns matched against an
already-lowercased title in beyondhd.py, unit3d_base.py, passthepopcorn.py,
and hdb.py. Because the pattern's literal tokens (AVC, HEVC, BD, Blu, ISO,
COMPLETE, ...) are upper/mixed-case, none of those copies could ever match a
real disc release -- the positive-match branches were dead code. Now there
is one shared, case-insensitive pattern; these tests lock in that every
consumer actually detects a disc release.
"""

import os
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

from pymediainfo import MediaInfo
import pytest

from src.backend.trackers.beyondhd import BHDUploader
from src.backend.trackers.passthepopcorn import PTPUploader
from src.backend.trackers.unit3d_base import Unit3dBaseUploader
from src.backend.trackers.utils import DISC_TITLE_REGEX
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.trackers.aither import AitherCategory, AitherResolution, AitherType
from src.enums.trackers.beyondhd import BHDType
from src.enums.trackers.passthepopcorn import PTPCodec

_BD_25_SIZE = 20_000_000_000  # under the 25 GiB BD_25 threshold


def _fake_file_size(monkeypatch: pytest.MonkeyPatch, path: Path, size: int) -> None:
    """Make ``path.stat().st_size`` report ``size`` without allocating that
    much real disk (a real 20 GiB sparse file via os.truncate() takes 20+s
    per test on Windows/NTFS here -- stat() is the only thing `_type()`/
    `_get_codec()` under test actually read from the file)."""
    path.touch()
    real_stat = Path.stat
    real_size = path.stat().st_size

    def fake_stat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        result = real_stat(self, *args, **kwargs)
        if self == path and result.st_size == real_size:
            return os.stat_result(
                (
                    result.st_mode,
                    result.st_ino,
                    result.st_dev,
                    result.st_nlink,
                    result.st_uid,
                    result.st_gid,
                    size,
                    result.st_atime,
                    result.st_mtime,
                    result.st_ctime,
                )
            )
        return result

    monkeypatch.setattr(Path, "stat", fake_stat)


@pytest.mark.parametrize(
    ("title", "should_match"),
    [
        ("movie.name.2024.1080p.bluray.avc-group", True),
        ("movie.name.2024.1080p.bluray.avc.dts-hd.ma.5.1-group", True),
        ("movie.name.2024.complete.bluray-group", True),
        ("movie.name.2024.2160p.uhd.bluray.hevc-group", True),
        # explicitly excluded encode/remux/rip signals must never match
        ("movie.name.2024.1080p.bdrip.x264-group", False),
        ("movie.name.2024.1080p.bluray.remux.avc-group", False),
        ("movie.name.2024.1080p.web-dl.h264-group", False),
        ("movie.name.2024.720p.bluray.x264-group", False),
    ],
)
def test_disc_title_regex_matches_case_insensitively(
    title: str, should_match: bool
) -> None:
    assert bool(DISC_TITLE_REGEX.search(title)) is should_match


def test_beyondhd_type_detects_disc_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "Movie.Name.2024.1080p.BluRay.AVC-GROUP.mkv"
    _fake_file_size(monkeypatch, input_path, _BD_25_SIZE)
    uploader = BHDUploader(
        api_key="api-key",
        torrent_file=tmp_path / "upload.torrent",
        input_path=input_path,
        media_type=MediaType.MOVIE,
    )

    assert uploader._type() == BHDType.BD_25.value


def test_beyondhd_disc_size_can_come_from_an_archive(tmp_path: Path) -> None:
    uploader = BHDUploader(
        api_key="api-key",
        torrent_file=tmp_path / "upload.torrent",
        input_path=tmp_path / "Movie.Name.2024.1080p.BluRay.AVC-GROUP.mkv",
        media_type=MediaType.MOVIE,
        content_size=_BD_25_SIZE,
    )

    assert not uploader.input_path.exists()
    assert uploader._type() == BHDType.BD_25.value


def test_unit3d_type_id_detects_disc_release(tmp_path: Path) -> None:
    uploader = Unit3dBaseUploader(
        tracker_name=TrackerSelection.AITHER,
        base_url="https://tracker.example",
        media_type=MediaType.MOVIE,
        api_key="api-key",
        torrent_file=tmp_path / "upload.torrent",
        input_path=tmp_path / "Movie.Name.2024.1080p.BluRay.AVC-GROUP.mkv",
        mediainfo_obj=cast(MediaInfo, object()),
        cat_enum=AitherCategory,
        res_enum=AitherResolution,
        type_enum=AitherType,
    )

    assert uploader._get_type_id() == AitherType.DISC.value


def test_passthepopcorn_codec_detects_disc_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "Movie.Name.2024.1080p.BluRay.AVC-GROUP.mkv"
    _fake_file_size(monkeypatch, input_path, _BD_25_SIZE)
    uploader = PTPUploader(
        username="user",
        password="password",  # noqa: S106 - test fixture, not a credential
        mediainfo_obj=MagicMock(),
        announce_url="https://tracker.example/announce",
        cookie_dir=tmp_path,
    )

    assert uploader._get_codec(input_path) == str(PTPCodec.BD25.value)
