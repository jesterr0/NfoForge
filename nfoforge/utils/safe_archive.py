"""Reading a zip archive that arrived from somewhere else.

A zip is a list of names and the bytes that go with them, and nothing in the
format stops a name being `../../autoexec.bat`, an absolute path, or a symlink
pointing at somewhere the archive does not own. `ZipFile.extractall` sanitises
paths, but it does so silently and it does not bound what it writes, so an
archive of a thousand nested empty directories or one file that decompresses to
fifty gigabytes is still a successful extraction.

Both places NfoForge accepts an archive -- a configuration bundle and a plugin
-- are handed one by a user who got it from a third party, so the same
questions have to be answered in both: does every name stay inside the
destination, is every entry an ordinary file, and is the whole thing a size
worth writing to disk. Answered here once so the two cannot answer them
differently.

Refusal is deliberate where sanitising would do. An archive containing
`../evil` is not one whose author made a mistake about relative paths, and
quietly extracting it to `evil` hides that from the person who has to decide
whether to trust it.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path, PurePosixPath
import stat
import zipfile

DEFAULT_MAX_ENTRIES = 4096
"""Enough for a plugin repository with its tests and documentation."""

DEFAULT_MAX_TOTAL_BYTES = 256 * 1024 * 1024
"""Uncompressed, summed across every entry."""

_CHUNK = 64 * 1024


class UnsafeArchiveError(Exception):
    """An archive was refused, before anything was read out of it."""


def member_path(info: zipfile.ZipInfo) -> PurePosixPath:
    """The relative path an entry names, or raise if it names anything else.

    Zip stores separators as `/` regardless of the platform that wrote it, so a
    backslash in a name is not a separator that needs converting -- it is a
    literal character that Windows will then treat as one. Refused rather than
    normalised, because the two readings put the file in different places.
    """
    raw = info.filename
    if not raw.strip():
        raise UnsafeArchiveError("The archive contains an entry with no name")
    if "\\" in raw:
        raise UnsafeArchiveError(
            f"The archive entry '{raw}' uses a backslash, which zip does not "
            "use as a separator"
        )
    candidate = PurePosixPath(raw)
    if candidate.is_absolute():
        raise UnsafeArchiveError(f"The archive entry '{raw}' is an absolute path")
    parts = candidate.parts
    if any(part == ".." for part in parts):
        raise UnsafeArchiveError(
            f"The archive entry '{raw}' points outside the archive"
        )
    if any(":" in part for part in parts):
        raise UnsafeArchiveError(
            f"The archive entry '{raw}' names a drive, which would place it "
            "outside the destination"
        )
    return candidate


def safe_members(
    archive: zipfile.ZipFile,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> tuple[zipfile.ZipInfo, ...]:
    """Every file entry in `archive`, having refused the whole archive if any
    one of them is unacceptable.

    All or nothing on purpose: an archive holding one hostile entry is not an
    archive to take the rest of on trust.

    Directory entries are dropped rather than returned. They carry no content,
    and the directories that are actually needed are created from the file
    names, so an archive that declares none -- which is common -- extracts the
    same way as one that declares them all.
    """
    entries = archive.infolist()
    if len(entries) > max_entries:
        raise UnsafeArchiveError(
            f"The archive holds {len(entries)} entries, more than the "
            f"{max_entries} allowed"
        )

    declared = 0
    members: list[zipfile.ZipInfo] = []
    for info in entries:
        member_path(info)
        # Only the type bits are consulted, and only when the writer set any.
        # `ZipFile.writestr` records permissions alone (0o600 << 16), so
        # treating a zero type as "not a regular file" would refuse archives
        # this application writes itself.
        file_type = stat.S_IFMT(info.external_attr >> 16)
        if file_type and file_type not in (stat.S_IFREG, stat.S_IFDIR):
            raise UnsafeArchiveError(
                f"The archive entry '{info.filename}' is a link or a device "
                "rather than an ordinary file"
            )
        if info.is_dir():
            continue
        declared += info.file_size
        if declared > max_total_bytes:
            raise UnsafeArchiveError(
                "The archive unpacks to more than "
                f"{max_total_bytes // (1024 * 1024)} MB"
            )
        members.append(info)
    return tuple(members)


def read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    max_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> bytes:
    """One entry's bytes, stopping rather than trusting its declared size.

    `file_size` comes out of the archive's own header, so a crafted archive can
    declare a kilobyte and deliver a gigabyte. The cap is applied to what is
    actually read.
    """
    with archive.open(info) as source:
        payload = source.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise UnsafeArchiveError(
            f"The archive entry '{info.filename}' is larger than it declares"
        )
    return payload


def extract_safely(
    archive: zipfile.ZipFile,
    destination: Path,
    members: Sequence[zipfile.ZipInfo],
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> None:
    """Write `members` below `destination`, and nowhere else.

    `members` is passed in rather than read here so that the caller has already
    been through `safe_members`; every name is therefore known to be relative
    and free of `..` before it is joined to anything. The resolved check below
    is the second lock on the same door, for the cases a name-level check does
    not see -- a reserved device name on Windows, a trailing dot the filesystem
    strips, a destination that is itself a symlink.
    """
    root = destination.resolve()
    written = 0
    for info in members:
        target = (destination / member_path(info)).resolve()
        if target != root and root not in target.parents:
            raise UnsafeArchiveError(
                f"The archive entry '{info.filename}' resolves outside the destination"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, open(target, "wb") as sink:
            while chunk := source.read(_CHUNK):
                written += len(chunk)
                if written > max_total_bytes:
                    raise UnsafeArchiveError(
                        "The archive unpacks to more than "
                        f"{max_total_bytes // (1024 * 1024)} MB"
                    )
                sink.write(chunk)
