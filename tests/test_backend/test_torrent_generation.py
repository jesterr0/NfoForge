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


def _fake_mkbrr(monkeypatch: pytest.MonkeyPatch, captured: list[str]) -> None:
    """Stand in for the mkbrr binary, recording the argv it was handed."""
    process = MagicMock()
    process.__enter__.return_value = process
    process.__exit__.return_value = False
    process.stdout = StringIO("Wrote torrent\n")
    process.returncode = 0

    def fake_popen(command: list[str], **_kwargs: Any) -> MagicMock:
        captured.extend(command)
        return process

    monkeypatch.setattr(torrent_module.subprocess, "Popen", fake_popen)


@pytest.mark.parametrize(
    ("announce_url", "expects_flag"),
    [
        ("https://tracker.invalid/announce", True),
        (None, False),
        ("", False),
    ],
)
def test_mkbrr_omits_the_tracker_flag_when_there_is_no_announce_url(
    announce_url: str | None,
    expects_flag: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A growing number of UNIT3D trackers hand out no announce URL at all --
    they stamp their own into the torrent they return on upload. mkbrr's
    --tracker is optional (verified against mkbrr 1.21.0: it writes a valid
    private torrent with no announce key), so NfoForge must drop the flag
    rather than refuse to build the torrent."""
    _, media = _release_with_indexes(tmp_path)
    output_path = tmp_path / "output.torrent"
    expected = Torrent(path=media)
    expected.generate()
    expected.write(output_path)
    captured_command: list[str] = []
    _fake_mkbrr(monkeypatch, captured_command)

    result = mkbrr_generate_torrent(
        mkbrr_path=tmp_path / "mkbrr.exe",
        tracker_info=TrackerInfo(announce_url=announce_url),
        path=media,
        output_path=output_path,
        max_piece_size=None,
        cb=lambda _progress: None,
    )

    assert result is not None
    assert ("--tracker" in captured_command) is expects_flag
    if expects_flag:
        assert captured_command[captured_command.index("--tracker") + 1] == announce_url
    # --output is always explicit, so dropping --tracker cannot change where
    # the torrent lands (mkbrr only derives a tracker-domain filename prefix
    # when it picks the name itself)
    assert captured_command[captured_command.index("--output") + 1] == str(output_path)


def test_clone_strips_the_base_announce_for_a_tracker_without_one(
    tmp_path: Path,
) -> None:
    """The base torrent belongs to whichever tracker was hashed first. Leaving
    its announce in place would hand a tracker that has none a torrent pointing
    at a different tracker -- which is what shipped before, since the announce
    was only ever overwritten, never cleared."""
    _, media = _release_with_indexes(tmp_path)
    base_path = tmp_path / "base.torrent"
    base = generate_torrent(
        tracker_info=TrackerInfo(
            announce_url="https://first.invalid/PASSKEY/announce", source="First"
        ),
        path=media,
        max_piece_size=None,
        cb=lambda *_args: None,
    )
    base.write(base_path, overwrite=True)
    assert base.trackers

    clone = torrent_module.clone_torrent(
        tracker_info=TrackerInfo(announce_url=None, source="Second"),
        torrent_path=tmp_path / "second.torrent",
        base_torrent_file=base_path,
    )

    assert clone.trackers == []
    assert "announce" not in clone.metainfo
    assert "announce-list" not in clone.metainfo
    # the rest of the clone must be untouched
    assert clone.private is True
    assert clone.metainfo["info"]["source"] == "Second"  # pyright: ignore[reportTypedDictNotRequiredAccess]


def test_clone_strips_the_base_comment_and_source_for_a_tracker_without_them(
    tmp_path: Path,
) -> None:
    """Same leak as the announce, one field over. The comment and source belong
    to whichever tracker was hashed first, so a tracker that configures neither
    used to ship the first tracker's comment to its users -- visible in any
    torrent client -- and its source tag, which changes the infohash."""
    _, media = _release_with_indexes(tmp_path)
    base_path = tmp_path / "base.torrent"
    base = generate_torrent(
        tracker_info=TrackerInfo(
            announce_url="https://first.invalid/PASSKEY/announce",
            source="First",
            comments="Uploaded to First",
        ),
        path=media,
        max_piece_size=None,
        cb=lambda *_args: None,
    )
    base.write(base_path, overwrite=True)
    assert base.comment == "Uploaded to First"

    clone = torrent_module.clone_torrent(
        tracker_info=TrackerInfo(
            announce_url="https://second.invalid/OTHERKEY/announce",
            source=None,
            comments=None,
        ),
        torrent_path=tmp_path / "second.torrent",
        base_torrent_file=base_path,
    )

    assert clone.comment is None
    assert "comment" not in clone.metainfo
    assert "source" not in clone.metainfo["info"]
    # the rest of the clone must be untouched
    assert clone.private is True
    assert clone.trackers == [["https://second.invalid/OTHERKEY/announce"]]


def test_clone_still_overwrites_the_comment_and_source_when_the_tracker_has_them(
    tmp_path: Path,
) -> None:
    """The normal path must be unaffected."""
    _, media = _release_with_indexes(tmp_path)
    base_path = tmp_path / "base.torrent"
    base = generate_torrent(
        tracker_info=TrackerInfo(
            announce_url="https://first.invalid/PASSKEY/announce",
            source="First",
            comments="Uploaded to First",
        ),
        path=media,
        max_piece_size=None,
        cb=lambda *_args: None,
    )
    base.write(base_path, overwrite=True)

    clone = torrent_module.clone_torrent(
        tracker_info=TrackerInfo(
            announce_url="https://second.invalid/OTHERKEY/announce",
            source="Second",
            comments="Uploaded to Second",
        ),
        torrent_path=tmp_path / "second.torrent",
        base_torrent_file=base_path,
    )

    assert clone.comment == "Uploaded to Second"
    assert clone.metainfo["info"]["source"] == "Second"  # pyright: ignore[reportTypedDictNotRequiredAccess]


def test_clone_still_overwrites_the_announce_when_the_tracker_has_one(
    tmp_path: Path,
) -> None:
    """The normal path must be unaffected."""
    _, media = _release_with_indexes(tmp_path)
    base_path = tmp_path / "base.torrent"
    base = generate_torrent(
        tracker_info=TrackerInfo(
            announce_url="https://first.invalid/PASSKEY/announce", source="First"
        ),
        path=media,
        max_piece_size=None,
        cb=lambda *_args: None,
    )
    base.write(base_path, overwrite=True)

    clone = torrent_module.clone_torrent(
        tracker_info=TrackerInfo(
            announce_url="https://second.invalid/OTHERKEY/announce", source="Second"
        ),
        torrent_path=tmp_path / "second.torrent",
        base_torrent_file=base_path,
    )

    assert clone.trackers == [["https://second.invalid/OTHERKEY/announce"]]
