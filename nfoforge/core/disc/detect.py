"""Decide whether an input folder is a disc, and read what is on it."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path

from nfoforge.core.disc.dvd import DurationReader, ifo_duration, read_title_sets
from nfoforge.core.disc.model import Disc, DiscError, DiscPlaylist, DiscType
from nfoforge.core.disc.mount import MOUNTS, MountRegistry, is_disc_image
from nfoforge.core.disc.mpls import read_playlists

_MARKERS = {"bdmv": DiscType.BDMV, "video_ts": DiscType.DVD}

#: How far a playlist's runtime may sit from the largest one's and still be
#: offered as a main feature: a theatrical and an extended cut, say.
_MAIN_RUNTIME_WINDOW = (0.7, 1.3)


def detect_disc(
    input_path: Path,
    duration_reader: DurationReader = ifo_duration,
    mounts: MountRegistry | None = None,
) -> Disc | None:
    """The disc at `input_path`, or ``None`` when it is not a disc.

    A disc folder, a folder holding one, or a disc image (`.iso`), which is
    mounted to be read and stays mounted (see `mount.MOUNTS`).

    Raises `DiscError` for input that is disc-shaped but unusable, so the user
    is told why rather than having its clips treated as loose video files.
    """
    if is_disc_image(input_path):
        return read_disc_image(input_path, duration_reader, mounts or MOUNTS)
    discs = find_discs(input_path, duration_reader)
    if not discs:
        return None
    if len(discs) > 1:
        names = ", ".join(disc.label for disc in discs)
        raise DiscError(
            f"{input_path.name} holds {len(discs)} discs ({names}). "
            "Multi-disc sets are not supported yet: select one disc folder."
        )
    return discs[0]


def find_discs(
    input_path: Path, duration_reader: DurationReader = ifo_duration
) -> list[Disc]:
    """Every disc in `input_path`: the folder itself, or its direct subfolders."""
    if not input_path.is_dir():
        return []
    if input_path.name.casefold() in _MARKERS:
        raise DiscError(
            f"Select the folder that contains {input_path.name}, "
            "not the folder itself: the whole disc is what gets uploaded."
        )

    own = _markers_in(input_path)
    if own:
        return [_read_disc(input_path, own, duration_reader)]

    discs = [
        _read_disc(child, markers, duration_reader)
        for child in sorted(_subdirs(input_path))
        if (markers := _markers_in(child))
    ]
    if len({disc.disc_type for disc in discs}) > 1:
        raise DiscError(
            f"{input_path.name} mixes Blu-ray and DVD discs, "
            "which cannot be uploaded as one release."
        )
    return discs


def read_disc_image(
    image: Path, duration_reader: DurationReader, mounts: MountRegistry
) -> Disc:
    """The disc inside `image`, which is left mounted for reading.

    The image is what gets uploaded, so it sizes and names the disc.
    """
    root = mounts.mount(image)
    try:
        markers = _markers_in(root)
        if not markers:
            raise DiscError(
                f"{image.name} holds no Blu-ray or DVD (no BDMV or VIDEO_TS folder)."
            )
        disc = _read_disc(
            root,
            markers,
            duration_reader,
            label=image.stem,
            size=image.stat().st_size,
        )
    except (DiscError, OSError):
        mounts.release(image)
        raise
    disc.image = image
    return disc


def holds_disc(folder: Path) -> bool:
    """Whether `folder` is a disc, or holds one directly: a cheap check, no reading.

    For callers that only need to know a folder's clips are not loose videos.
    """
    if not folder.is_dir():
        return False
    return bool(_markers_in(folder)) or any(
        _markers_in(child) for child in _subdirs(folder)
    )


def mark_main_playlists(playlists: Sequence[DiscPlaylist]) -> None:
    """Flag the main feature, and any alternate cut of it.

    The largest playlist is the feature: size is always known, while a runtime
    can be missing or wrong. Anything close to it in runtime is flagged too.
    """
    for playlist in playlists:
        playlist.is_main = False
    if not playlists:
        return
    largest = max(playlists, key=lambda playlist: playlist.size)
    largest.is_main = True
    if not largest.duration:
        return
    low, high = (largest.duration * factor for factor in _MAIN_RUNTIME_WINDOW)
    for playlist in playlists:
        if playlist.duration and low <= playlist.duration <= high:
            playlist.is_main = True


def directory_size(root: Path) -> int:
    total = 0
    for folder, _, files in os.walk(root):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(folder, name))
            except OSError:
                continue
    return total


def _read_disc(
    root: Path,
    markers: dict[DiscType, Path],
    duration_reader: DurationReader,
    *,
    label: str | None = None,
    size: int | None = None,
) -> Disc:
    # a mounted image's root is a drive or mount point: its name says nothing
    label = label or root.name
    if len(markers) > 1:
        raise DiscError(f"{label} has both a BDMV and a VIDEO_TS folder.")
    disc_type, marker = next(iter(markers.items()))

    has_certificate: bool | None = None
    if disc_type is DiscType.BDMV:
        playlist_dir = _child(marker, "playlist")
        if playlist_dir is None:
            raise DiscError(f"{label} has no BDMV/PLAYLIST folder.")
        playlists = read_playlists(playlist_dir, _child(marker, "stream"))
        has_certificate = _child(root, "certificate") is not None
    else:
        playlists = read_title_sets(marker, duration_reader)

    if not playlists:
        raise DiscError(f"Nothing playable was found on {label}.")
    mark_main_playlists(playlists)
    return Disc(
        root=root,
        disc_type=disc_type,
        label=label,
        size=directory_size(root) if size is None else size,
        playlists=playlists,
        has_certificate=has_certificate,
    )


def _markers_in(folder: Path) -> dict[DiscType, Path]:
    return {
        _MARKERS[child.name.casefold()]: child
        for child in _subdirs(folder)
        if child.name.casefold() in _MARKERS
    }


def _child(folder: Path, name: str) -> Path | None:
    """A subfolder by name, whatever case the disc was ripped in."""
    for child in _subdirs(folder):
        if child.name.casefold() == name:
            return child
    return None


def _subdirs(folder: Path) -> list[Path]:
    try:
        return [child for child in folder.iterdir() if child.is_dir()]
    except OSError:
        return []
