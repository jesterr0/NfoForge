"""Every way an archive is refused before anything is read out of it.

Written against tiny caps rather than the real ones so that the size and count
limits can be proved without building a 32 MB file, and so the test says what
it is testing rather than what the current constant happens to be.
"""

from pathlib import Path
import zipfile

import pytest

from src.utils.safe_archive import (
    UnsafeArchiveError,
    extract_safely,
    member_path,
    read_member,
    safe_members,
)


def _zip(path: Path, entries: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return path


def test_an_ordinary_archive_is_accepted(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "ok.zip", {"a.txt": "one", "nested/b.txt": "two"})
    with zipfile.ZipFile(archive) as opened:
        members = safe_members(opened)
    assert sorted(info.filename for info in members) == ["a.txt", "nested/b.txt"]


def test_directory_entries_are_dropped_rather_than_returned(tmp_path: Path) -> None:
    with zipfile.ZipFile(tmp_path / "dirs.zip", "w") as archive:
        archive.writestr("folder/", "")
        archive.writestr("folder/a.txt", "one")
    with zipfile.ZipFile(tmp_path / "dirs.zip") as opened:
        members = safe_members(opened)
    assert [info.filename for info in members] == ["folder/a.txt"]


@pytest.mark.parametrize(
    "name",
    (
        "../escape.txt",
        "nested/../../escape.txt",
        "/absolute.txt",
        "C:/drive.txt",
    ),
)
def test_a_name_that_could_leave_the_destination_is_refused(
    tmp_path: Path, name: str
) -> None:
    archive = _zip(tmp_path / "bad.zip", {name: "payload"})
    with zipfile.ZipFile(archive) as opened, pytest.raises(UnsafeArchiveError):
        safe_members(opened)


def test_a_backslash_in_a_name_is_refused() -> None:
    """Zip separates with `/`; a backslash is a character Windows reads as a
    separator and other platforms do not.

    Checked against a `ZipInfo` rather than a file on disk because `zipfile`
    normalises the separator as it writes, so this shape cannot be produced
    locally -- only received in somebody else's archive.
    """
    info = zipfile.ZipInfo("placeholder")
    info.filename = "windows\\separator.txt"
    with pytest.raises(UnsafeArchiveError):
        member_path(info)


def test_an_unnamed_entry_is_refused() -> None:
    info = zipfile.ZipInfo("placeholder")
    info.filename = "   "
    with pytest.raises(UnsafeArchiveError):
        member_path(info)


def test_a_symlink_entry_is_refused(tmp_path: Path) -> None:
    info = zipfile.ZipInfo("link")
    # The high half of external_attr is the Unix mode; 0o120000 is S_IFLNK.
    info.external_attr = (0o120777) << 16
    with zipfile.ZipFile(tmp_path / "link.zip", "w") as archive:
        archive.writestr(info, "/etc/passwd")
    with (
        zipfile.ZipFile(tmp_path / "link.zip") as opened,
        pytest.raises(UnsafeArchiveError),
    ):
        safe_members(opened)


def test_too_many_entries_is_refused(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "many.zip", {f"{index}.txt": "x" for index in range(6)})
    with zipfile.ZipFile(archive) as opened, pytest.raises(UnsafeArchiveError):
        safe_members(opened, max_entries=5)


def test_too_large_uncompressed_is_refused(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "big.zip", {"a.txt": "x" * 100})
    with zipfile.ZipFile(archive) as opened, pytest.raises(UnsafeArchiveError):
        safe_members(opened, max_total_bytes=10)


def test_a_member_larger_than_it_declares_is_refused(tmp_path: Path) -> None:
    """The declared size lives in the archive's own header, so it can lie."""
    archive = _zip(tmp_path / "liar.zip", {"a.txt": "x" * 100})
    with zipfile.ZipFile(archive) as opened:
        info = opened.getinfo("a.txt")
        with pytest.raises(UnsafeArchiveError):
            read_member(opened, info, max_bytes=10)


def test_extraction_writes_only_below_the_destination(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "ok.zip", {"a.txt": "one", "nested/b.txt": "two"})
    destination = tmp_path / "out"
    destination.mkdir()
    with zipfile.ZipFile(archive) as opened:
        extract_safely(opened, destination, safe_members(opened))

    assert (destination / "a.txt").read_text(encoding="utf-8") == "one"
    assert (destination / "nested" / "b.txt").read_text(encoding="utf-8") == "two"
    assert not (tmp_path / "escape.txt").exists()


def test_extraction_stops_at_the_byte_budget(tmp_path: Path) -> None:
    """The budget is applied to bytes actually written, not to the header."""
    archive = _zip(tmp_path / "big.zip", {"a.txt": "x" * 100})
    destination = tmp_path / "out"
    destination.mkdir()
    with zipfile.ZipFile(archive) as opened:
        members = safe_members(opened)
        with pytest.raises(UnsafeArchiveError):
            extract_safely(opened, destination, members, max_total_bytes=10)
