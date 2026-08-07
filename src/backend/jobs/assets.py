"""Copying everything a job needs into the job's own directory.

A saved job must not depend on `processing/`: that tree is what Settings ->
General "Clean Up" empties, so a job pointing into it is one housekeeping click
away from being useless. Every input a resumed run needs is therefore copied
beside the job and the saved document is re-pointed at those copies.

Three kinds of asset are captured:

- **Screenshots**, so a job can still upload images after a clean up. Copied
  even when the images were already uploaded and their URLs recorded, because
  changing a tracker's image host on resume invalidates those URLs and forces a
  fresh upload from local files.
- **MediaInfo**, as both the OLDXML that rebuilds the `MediaInfo` object and the
  plain-text dump trackers actually receive. Between them a resumed run never
  has to call `MediaInfo.parse()` against the media again.
- **The base torrent**, so a resumed run clones instead of re-hashing what may
  be tens of gigabytes. Recorded with the media's size and mtime so a changed
  file falls back to hashing rather than shipping stale piece hashes.

Qt-free, so it stays unit testable.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
from typing import Any

from pymediainfo import MediaInfo

from src.backend.jobs.codec import mediainfo_xml
from src.backend.jobs.store import (
    JOB_BASE_TORRENT_NAME,
    JOB_IMAGES_DIR_NAME,
    JOB_MEDIAINFO_DIR_NAME,
    JOB_NFO_DIR_NAME,
)
from src.enums.tracker_selection import TrackerSelection
from src.logger.nfo_forge_logger import LOG


class JobAssetError(Exception):
    """A job's supporting files could not be captured or restored."""


@dataclass(frozen=True, slots=True)
class MediaFingerprint:
    """Enough of a file's identity to tell whether it changed since a save.

    Size plus mtime is deliberately cheap: hashing a multi-gigabyte remux to
    decide whether re-hashing can be skipped would defeat the point.
    """

    size: int
    mtime_ns: int

    @classmethod
    def of(cls, path: Path) -> MediaFingerprint:
        stat = path.stat()
        return cls(size=stat.st_size, mtime_ns=stat.st_mtime_ns)

    def matches(self, path: Path) -> bool:
        try:
            return self == MediaFingerprint.of(path)
        except OSError:
            return False

    def to_dict(self) -> dict[str, Any]:
        return {"size": self.size, "mtime_ns": self.mtime_ns}

    @classmethod
    def from_dict(cls, document: Any) -> MediaFingerprint | None:
        if not isinstance(document, dict):
            return None
        size, mtime_ns = document.get("size"), document.get("mtime_ns")
        if not isinstance(size, int) or not isinstance(mtime_ns, int):
            return None
        return cls(size=size, mtime_ns=mtime_ns)


def _unique_destination(directory: Path, name: str) -> Path:
    """Pick a free filename, so same-named files from different dirs coexist."""
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for index in range(1, 1000):
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise JobAssetError(f"Could not find a free filename for '{name}' in {directory}")


def copy_images(directory: Path, images: list[Path]) -> list[Path]:
    """Copy screenshots into the job and return their new paths.

    A missing source is skipped with a warning rather than failing the save:
    losing one screenshot should not cost the user the whole job.
    """
    if not images:
        return []
    target = directory / JOB_IMAGES_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    for image in images:
        if not image.is_file():
            LOG.warning(
                LOG.LOG_SOURCE.BE, f"Skipping missing screenshot while saving: {image}"
            )
            continue
        destination = _unique_destination(target, image.name)
        try:
            shutil.copy2(image, destination)
        except OSError as error:
            raise JobAssetError(
                f"Could not copy screenshot '{image}': {error}"
            ) from error
        copied.append(destination)
    return copied


def capture_mediainfo(
    directory: Path, media_paths: list[Path]
) -> dict[Path, dict[str, str]]:
    """Store OLDXML and the plain-text dump for each media file.

    The XML rebuilds the `MediaInfo` object; the text dump is what trackers are
    actually sent (`MinimalMediaInfo.get_full_mi_str`) and cannot be derived
    from the object, since it comes from libmediainfo's own formatter. Keeping
    both is what lets a resumed run avoid touching the media file at all.
    """
    if not media_paths:
        return {}
    target = directory / JOB_MEDIAINFO_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)

    captured: dict[Path, dict[str, str]] = {}
    for index, media_path in enumerate(media_paths):
        try:
            xml = mediainfo_xml(media_path)
            text = MediaInfo.parse(
                media_path, full=False, output="", legacy_stream_display=True
            )
        except Exception as error:
            raise JobAssetError(
                f"Could not capture MediaInfo for '{media_path}': {error}"
            ) from error

        xml_path = target / f"{index}.xml"
        text_path = target / f"{index}.txt"
        try:
            # newline="" throughout: MediaInfo's text output uses CRLF, and
            # letting Python translate line endings on the way out and back in
            # corrupts it, so what a tracker receives would not match what was
            # captured
            _write_exact(xml_path, xml)
            _write_exact(text_path, str(text))
        except OSError as error:
            raise JobAssetError(
                f"Could not write MediaInfo for '{media_path}': {error}"
            ) from error

        captured[media_path] = {
            "xml": f"{JOB_MEDIAINFO_DIR_NAME}/{xml_path.name}",
            "text": f"{JOB_MEDIAINFO_DIR_NAME}/{text_path.name}",
        }
    return captured


def _write_exact(path: Path, text: str) -> None:
    """Write text without translating line endings."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def read_job_asset(directory: Path, name: str) -> str | None:
    """Read one stored sidecar by its job-relative name, or None if unavailable.

    Names are stored relative to the job directory (`mediainfo/0.xml`,
    `nfo/aither.txt`) so one loader serves every kind of asset. They come out of
    `job.json`, which is a user-writable file, so a name that escapes the job
    directory is refused rather than followed.
    """
    if not name:
        return None
    root = directory.resolve(strict=False)
    candidate = (directory / name).resolve(strict=False)
    if not candidate.is_relative_to(root):
        LOG.warning(
            LOG.LOG_SOURCE.BE,
            f"Refusing job asset outside its own directory: '{name}'",
        )
        return None
    try:
        with candidate.open("r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except OSError as error:
        LOG.warning(LOG.LOG_SOURCE.BE, f"Could not read stored job asset: {error}")
        return None


def capture_nfos(
    directory: Path, release_data: dict[TrackerSelection, dict[str, str | None]]
) -> dict[TrackerSelection, str]:
    """Store each tracker's finished NFO beside the job.

    NFOs are otherwise written under `processing/<tracker>/`, which Clean Up
    empties -- and a prepared job's whole point is that its NFO is the one that
    gets uploaded, so it cannot live somewhere disposable.
    """
    target = directory / JOB_NFO_DIR_NAME
    captured: dict[TrackerSelection, str] = {}

    for tracker, release in release_data.items():
        nfo = release.get("nfo")
        if not nfo:
            continue
        target.mkdir(parents=True, exist_ok=True)
        name = f"{tracker.name.lower()}.txt"
        try:
            _write_exact(target / name, nfo)
        except OSError as error:
            raise JobAssetError(
                f"Could not write NFO for '{tracker}': {error}"
            ) from error
        captured[tracker] = f"{JOB_NFO_DIR_NAME}/{name}"
    return captured


def template_fingerprint(text: str) -> str:
    """Stable digest of a template's contents.

    A prepared job's frozen NFO deliberately beats a since-edited template, so
    this only exists to let the load path say *which* template changed rather
    than letting the difference pass unnoticed.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def copy_base_torrent(directory: Path, torrent: Path) -> Path | None:
    """Copy a generated torrent in as the clone source for future runs."""
    if not torrent.is_file():
        return None
    destination = directory / JOB_BASE_TORRENT_NAME
    try:
        shutil.copy2(torrent, destination)
    except OSError as error:
        LOG.warning(LOG.LOG_SOURCE.BE, f"Could not store base torrent for job: {error}")
        return None
    return destination


def base_torrent_path(directory: Path) -> Path | None:
    """The stored base torrent, if this job has one."""
    candidate = directory / JOB_BASE_TORRENT_NAME
    return candidate if candidate.is_file() else None


def torrent_content_files(input_path: Path) -> list[Path]:
    """Every file the generated torrent covers, in a stable order.

    Walks the input rather than reading `MediaInputPayload.file_list`: the
    torrent is built from `input_path`, so for a pack it also covers subtitles
    and other extras that the media file list leaves out.
    """
    if input_path.is_dir():
        return sorted(path for path in input_path.rglob("*") if path.is_file())
    return [input_path] if input_path.is_file() else []


def fingerprint_files(paths: Iterable[Path]) -> dict[str, dict[str, int]]:
    """Size and mtime for each path, keyed by its string form."""
    captured: dict[str, dict[str, int]] = {}
    for path in paths:
        try:
            captured[str(path)] = MediaFingerprint.of(path).to_dict()
        except OSError as error:
            raise JobAssetError(f"Could not fingerprint '{path}': {error}") from error
    return captured


def fingerprints_match(stored: Any, input_path: Path) -> bool:
    """Whether every file the torrent covers is unchanged since it was recorded.

    The recorded set has to match exactly. A file added to or removed from a
    pack changes the torrent just as surely as an edited one does, and a clone
    made from a stale base uploads a torrent that does not describe its own
    content.
    """
    if not isinstance(stored, dict) or not stored:
        return False
    if {str(path) for path in torrent_content_files(input_path)} != set(stored):
        return False
    for raw_path, raw_fingerprint in stored.items():
        fingerprint = MediaFingerprint.from_dict(raw_fingerprint)
        if fingerprint is None or not fingerprint.matches(Path(raw_path)):
            return False
    return True
