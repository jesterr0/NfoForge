from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from torf import Torrent

from src.backend.torrents import torrent as torrent_module
from src.backend.torrents.torrent import (
    INDEX_SIDECAR_GLOBS,
    NFO_FORGE_CREATOR,
    _validate_torrent_contents,
    content_size,
    generate_torrent,
    mkbrr_generate_torrent,
    neutralize_base,
    write_torrent,
)
from src.payloads.trackers import TrackerInfo

# small enough to hash instantly, large enough to span several pieces at 2^16
_EXPONENT = 16


def _release_with_indexes(tmp_path: Path) -> tuple[Path, Path]:
    release = tmp_path / "Release"
    release.mkdir()
    media = release / "Movie.mkv"
    media.write_bytes(b"media")
    (release / "Movie.lwi").write_bytes(b"lsmash index")
    (release / "Movie.ffindex").write_bytes(b"ffms2 index")
    return release, media


def _base_torrent(tmp_path: Path, media: Path) -> Path:
    """A neutral base on disk, as the run would produce it."""
    base_path = tmp_path / "base.torrent"
    base = generate_torrent(
        path=media, piece_exponent=_EXPONENT, cb=lambda *_args: None
    )
    base.write(base_path, overwrite=True)
    return base_path


def test_torf_excludes_index_sidecars_without_removing_them(tmp_path: Path) -> None:
    release, _ = _release_with_indexes(tmp_path)

    torrent = generate_torrent(
        path=release,
        piece_exponent=_EXPONENT,
        cb=lambda *_args: None,
    )

    suffixes = {Path(str(file)).suffix.casefold() for file in torrent.files}
    assert ".lwi" not in suffixes
    assert ".ffindex" not in suffixes
    assert (release / "Movie.lwi").is_file()
    assert (release / "Movie.ffindex").is_file()


def test_content_size_counts_only_what_the_torrent_will_contain(
    tmp_path: Path,
) -> None:
    """The piece size is chosen from this number, so a release near a band
    boundary must not be sized from a total that includes excluded files."""
    release, media = _release_with_indexes(tmp_path)

    assert content_size(release) == media.stat().st_size


def test_torrent_content_validation_rejects_index_sidecars(tmp_path: Path) -> None:
    release, _ = _release_with_indexes(tmp_path)
    torrent = Torrent(path=release)
    torrent.generate()

    with pytest.raises(ValueError, match="excluded index sidecar"):
        _validate_torrent_contents(torrent)


# --------------------------------------------------------------------------
# the base is neutral
# --------------------------------------------------------------------------
def test_the_torf_base_carries_no_tracker_identity(tmp_path: Path) -> None:
    """The base is cloned for every tracker, so it must belong to none of them.
    It is also never uploaded, which is what stops a tracker's server appending
    an "Edited by" to its `created by`."""
    _, media = _release_with_indexes(tmp_path)

    torrent = generate_torrent(
        path=media, piece_exponent=_EXPONENT, cb=lambda *_args: None
    )

    assert "announce" not in torrent.metainfo
    assert "announce-list" not in torrent.metainfo
    assert "comment" not in torrent.metainfo
    assert "source" not in torrent.metainfo["info"]
    assert torrent.private is True
    assert torrent.metainfo["created by"] == NFO_FORGE_CREATOR  # pyright: ignore[reportTypedDictNotRequiredAccess]


def test_torf_honours_the_explicit_piece_exponent(tmp_path: Path) -> None:
    _, media = _release_with_indexes(tmp_path)

    torrent = generate_torrent(
        path=media, piece_exponent=_EXPONENT, cb=lambda *_args: None
    )

    assert torrent.piece_size == 2**_EXPONENT


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


def test_mkbrr_command_excludes_index_sidecars_and_validates_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, media = _release_with_indexes(tmp_path)
    output_path = tmp_path / "output.torrent"
    expected = Torrent(path=media)
    expected.generate()
    expected.write(output_path)
    captured_command: list[str] = []
    _fake_mkbrr(monkeypatch, captured_command)

    result = mkbrr_generate_torrent(
        mkbrr_path=tmp_path / "mkbrr.exe",
        path=release,
        output_path=output_path,
        piece_exponent=_EXPONENT,
        cb=lambda _progress: None,
    )

    assert result is not None
    exclude_values = [
        captured_command[index + 1]
        for index, value in enumerate(captured_command)
        if value == "--exclude"
    ]
    assert tuple(exclude_values) == INDEX_SIDECAR_GLOBS


def test_the_mkbrr_command_asks_for_no_tracker_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passing --tracker was the root of the bug this design fixes: it made the
    base one tracker's artifact, and it let that tracker's piece size rules
    decide the shape of a torrent every other tracker would share."""
    _, media = _release_with_indexes(tmp_path)
    output_path = tmp_path / "output.torrent"
    expected = Torrent(path=media)
    expected.generate()
    expected.write(output_path)
    captured_command: list[str] = []
    _fake_mkbrr(monkeypatch, captured_command)

    result = mkbrr_generate_torrent(
        mkbrr_path=tmp_path / "mkbrr.exe",
        path=media,
        output_path=output_path,
        piece_exponent=_EXPONENT,
        cb=lambda _progress: None,
    )

    assert result is not None
    assert "--tracker" not in captured_command
    assert "--source" not in captured_command
    assert "--comment" not in captured_command
    assert "--private" in captured_command
    # --piece-length is exact; the retired --max-piece-length was only a ceiling
    assert "--max-piece-length" not in captured_command
    assert captured_command[captured_command.index("--piece-length") + 1] == str(
        _EXPONENT
    )
    assert captured_command[captured_command.index("--output") + 1] == str(output_path)


# --------------------------------------------------------------------------
# stamping
# --------------------------------------------------------------------------
def test_clone_strips_the_base_announce_for_a_tracker_without_one(
    tmp_path: Path,
) -> None:
    """A tracker that has no announce URL must end up with no announce at all,
    rather than inheriting whatever the source torrent carried."""
    _, media = _release_with_indexes(tmp_path)
    base_path = tmp_path / "stamped.torrent"
    base = generate_torrent(
        path=media, piece_exponent=_EXPONENT, cb=lambda *_args: None
    )
    base.metainfo["announce"] = "https://first.invalid/PASSKEY/announce"
    base.metainfo["info"]["source"] = "First"
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
    """Same leak as the announce, one field over. A stale comment is visible in
    any torrent client, and a stale source tag changes the infohash."""
    _, media = _release_with_indexes(tmp_path)
    base_path = tmp_path / "stamped.torrent"
    base = generate_torrent(
        path=media, piece_exponent=_EXPONENT, cb=lambda *_args: None
    )
    base.metainfo["announce"] = "https://first.invalid/PASSKEY/announce"
    base.metainfo["info"]["source"] = "First"
    base.comment = "Uploaded to First"
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
    base_path = _base_torrent(tmp_path, media)

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
    base_path = _base_torrent(tmp_path, media)

    clone = torrent_module.clone_torrent(
        tracker_info=TrackerInfo(
            announce_url="https://second.invalid/OTHERKEY/announce", source="Second"
        ),
        torrent_path=tmp_path / "second.torrent",
        base_torrent_file=base_path,
    )

    assert clone.trackers == [["https://second.invalid/OTHERKEY/announce"]]


def test_clone_leaves_created_by_alone(tmp_path: Path) -> None:
    """`created by` names whichever tool hashed the base. Stamping must not
    touch it -- and because the base is never uploaded, nothing else can
    append to it either, which is what stops the "Edited by X. Edited by Y"
    chain the old shared-artifact base accumulated."""
    _, media = _release_with_indexes(tmp_path)
    base_path = _base_torrent(tmp_path, media)

    clone = torrent_module.clone_torrent(
        tracker_info=TrackerInfo(
            announce_url="https://second.invalid/OTHERKEY/announce", source="Second"
        ),
        torrent_path=tmp_path / "second.torrent",
        base_torrent_file=base_path,
    )

    assert clone.metainfo["created by"] == NFO_FORGE_CREATOR  # pyright: ignore[reportTypedDictNotRequiredAccess]


# --------------------------------------------------------------------------
# neutralizing a carried base
# --------------------------------------------------------------------------
def test_a_legacy_stamped_base_is_stripped_and_its_creator_reset(
    tmp_path: Path,
) -> None:
    """A base saved before neutral bases existed is a tracker's artifact -- for
    a UNIT3D tracker, the copy that tracker's server rewrote and handed back.
    Every field it carries, `created by` included, is that tracker's."""
    _, media = _release_with_indexes(tmp_path)
    legacy_path = tmp_path / "legacy.torrent"
    legacy = generate_torrent(
        path=media, piece_exponent=_EXPONENT, cb=lambda *_args: None
    )
    legacy.metainfo["announce"] = "https://first.invalid/PASSKEY/announce"
    legacy.metainfo["info"]["source"] = "First"
    legacy.comment = "Uploaded to First"
    legacy.metainfo["created by"] = "mkbrr/1.24.0. Edited by LST.GG"
    legacy.write(legacy_path, overwrite=True)
    expected_pieces = legacy.metainfo["info"]["pieces"]

    destination = tmp_path / "media.base.torrent"
    result = neutralize_base(legacy_path, destination)

    assert result == destination
    neutralized = Torrent.read(destination)
    assert "announce" not in neutralized.metainfo
    assert "announce-list" not in neutralized.metainfo
    assert "comment" not in neutralized.metainfo
    assert "source" not in neutralized.metainfo["info"]
    assert neutralized.metainfo["created by"] == NFO_FORGE_CREATOR  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert neutralized.private is True
    # the expensive part must survive -- that is the whole point of carrying it
    assert neutralized.metainfo["info"]["pieces"] == expected_pieces
    # the job's own stored copy is left alone
    assert Torrent.read(legacy_path).metainfo["announce"]  # pyright: ignore[reportTypedDictNotRequiredAccess]


def test_an_already_neutral_base_round_trips_with_its_creator_intact(
    tmp_path: Path,
) -> None:
    """Detection is content-based: a neutral base has none of the stamped
    fields, so its `created by` is a hashing tool's name and worth keeping."""
    _, media = _release_with_indexes(tmp_path)
    base_path = _base_torrent(tmp_path, media)
    original = Torrent.read(base_path)
    original.metainfo["created by"] = "mkbrr/1.24.0 (https://github.com/autobrr/mkbrr)"
    write_torrent(Torrent.copy(original), base_path)

    destination = tmp_path / "media.base.torrent"
    neutralize_base(base_path, destination)

    neutralized = Torrent.read(destination)
    assert (
        neutralized.metainfo["created by"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
        == "mkbrr/1.24.0 (https://github.com/autobrr/mkbrr)"
    )
    assert neutralized.metainfo["info"]["pieces"] == original.metainfo["info"]["pieces"]
