"""What a disc release is made of.

A release is a list of discs, never a single "is a disc" flag: a box set is
several discs, and each one has its own playlists, its own main feature and its
own report. Only single-disc releases are accepted for now, but nothing here
assumes that.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path

from nfoforge.core.disc.bdinfo_report import BDInfoReport


class DiscError(Exception):
    """An input that looks like a disc but cannot be used as one."""


class DiscType(StrEnum):
    """String values, because a disc is recorded in saved jobs."""

    BDMV = "bdmv"
    DVD = "dvd"


@dataclass(frozen=True, slots=True)
class PlaylistItem:
    """One clip a playlist plays: an `.m2ts` on a Blu-ray, a `.VOB` on a DVD."""

    path: Path
    size: int
    # seconds this playlist spends in the clip; unknown for a DVD's VOBs, whose
    # runtime is only known for the title set as a whole
    duration: float | None = None


@dataclass(slots=True)
class DiscPlaylist:
    """Something on a disc that plays from start to finish.

    A Blu-ray `.mpls`, or a DVD title set (`VTS_nn`). Both are "a list of
    clips with a runtime", which is all the rest of the pipeline needs.
    """

    playlist_id: str
    # the `.mpls`, or the title set's `VTS_nn_0.IFO` (absent on a damaged DVD)
    path: Path | None
    duration: float | None
    items: list[PlaylistItem] = field(default_factory=list)
    is_main: bool = False

    @property
    def size(self) -> int:
        """Bytes on disc, counting a clip once however often it is played."""
        return sum({item.path: item.size for item in self.items}.values())

    @property
    def largest_item(self) -> PlaylistItem | None:
        return max(self.items, key=lambda item: item.size, default=None)


@dataclass(slots=True)
class Disc:
    # the folder that holds `BDMV` / `VIDEO_TS`: what gets uploaded, unless the
    # disc is an image, in which case it is where the image is mounted
    root: Path
    disc_type: DiscType
    label: str
    size: int
    playlists: list[DiscPlaylist] = field(default_factory=list)
    selected: list[str] = field(default_factory=list)
    # Blu-ray only: some trackers refuse a disc without its `CERTIFICATE` folder
    has_certificate: bool | None = None
    # what describes the disc to a tracker, filled in once a playlist is
    # settled: a BDInfo scan for a Blu-ray, IFO and VOB MediaInfo for a DVD
    bdinfo: BDInfoReport | None = None
    ifo_mediainfo: str = ""
    vob_mediainfo: str = ""
    # the `.iso` the disc was read from: what gets uploaded, and what has to
    # be mounted again for `root` to lead anywhere
    image: Path | None = None

    @property
    def is_image(self) -> bool:
        return self.image is not None

    def playlist(self, playlist_id: str) -> DiscPlaylist | None:
        wanted = normalize_playlist_id(playlist_id)
        for playlist in self.playlists:
            if playlist.playlist_id == wanted:
                return playlist
        return None

    def main_playlists(self) -> list[DiscPlaylist]:
        return [playlist for playlist in self.playlists if playlist.is_main]

    def selected_playlists(self) -> list[DiscPlaylist]:
        found = (self.playlist(playlist_id) for playlist_id in self.selected)
        return [playlist for playlist in found if playlist is not None]

    def select(self, playlist_id: str) -> DiscPlaylist:
        playlist = self.playlist(playlist_id)
        if playlist is None:
            known = ", ".join(p.playlist_id for p in self.playlists) or "none"
            raise DiscError(
                f"'{playlist_id}' is not a playlist on {self.label} (found: {known})"
            )
        self.selected = [playlist.playlist_id]
        return playlist

    def relocate(self, remap: Callable[[Path], Path]) -> None:
        """Re-point every path the disc holds, after its folder or image was
        renamed, or its image mounted somewhere else."""
        self.root = remap(self.root)
        if self.image is not None:
            self.image = remap(self.image)
        for playlist in self.playlists:
            if playlist.path is not None:
                playlist.path = remap(playlist.path)
            playlist.items = [
                replace(item, path=remap(item.path)) for item in playlist.items
            ]

    def primary_media_file(self) -> Path | None:
        """The one clip that stands in for the disc where a single file is needed.

        MediaInfo and screenshots work on a file. For a Blu-ray that is the
        selected playlist's largest clip; for a DVD it is the title set's first
        feature VOB (`VTS_nn_1.VOB`), the menu VOB (`_0`) never.
        """
        chosen = self.selected_playlists() or self.main_playlists()
        if not chosen:
            return None
        playlist = chosen[0]
        if self.disc_type is DiscType.DVD:
            feature = [item for item in playlist.items if not is_menu_vob(item.path)]
            return feature[0].path if feature else None
        largest = playlist.largest_item
        return largest.path if largest else None


def disc_warnings(disc: Disc) -> list[str]:
    """What is wrong with `disc` that should be said, but does not stop an upload."""
    warnings: list[str] = []
    if disc.has_certificate is False:
        warnings.append(
            f"{disc.label} has no CERTIFICATE folder. Some trackers refuse a "
            "full Blu-ray without it."
        )
    return warnings


def normalize_playlist_id(playlist_id: str) -> str:
    """`800`, `00800` and `00800.MPLS` all name the same playlist."""
    text = playlist_id.strip().casefold()
    for suffix in (".mpls", ".ifo"):
        text = text.removesuffix(suffix)
    if text.startswith("vts_"):
        text = text.removeprefix("vts_").split("_")[0]
        return text.zfill(2)
    if text.isdigit():
        # a DVD title set is two digits, a Blu-ray playlist five
        return text.zfill(2) if len(text) <= 2 else text.zfill(5)
    return text


def is_menu_vob(path: Path) -> bool:
    """`VTS_nn_0.VOB` holds the title set's menus, not the feature."""
    return path.stem.casefold().endswith("_0")
