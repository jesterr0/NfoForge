"""Read a Blu-ray's playlists without scanning the disc.

A full BDInfo scan reads every stream on the disc and takes minutes. The
`.mpls` files are a few kilobytes each and already say which clips each
playlist plays and for how long, which is enough to find the main feature and
then scan only that.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import struct

from nfoforge.core.disc.model import DiscPlaylist, PlaylistItem

#: Playlist times are counted in ticks of a 45 kHz clock.
_TICKS_PER_SECOND = 45000.0

#: Below this a playlist is a menu loop, a logo or a trailer.
MIN_PLAYLIST_SECONDS = 180.0

#: A playlist that plays the same stretch of the same clip more than this many
#: times is a loop (menu backgrounds, or padding on a protected disc).
_MAX_REPEATS = 2


class MplsError(Exception):
    """A `.mpls` that is not a playlist file, or is cut short."""


def parse_mpls(data: bytes) -> list[tuple[str, int, int]]:
    """The `(clip name, in, out)` of every play item, times in 45 kHz ticks.

    Only the first angle of a multi-angle item is read: the others are
    alternative pictures for the same stretch, not more runtime.
    """
    if len(data) < 12 or data[:4] != b"MPLS":
        raise MplsError("not an MPLS playlist")
    (playlist_start,) = struct.unpack_from(">I", data, 8)
    try:
        # length (4), reserved (2), play item count (2), sub path count (2)
        (item_count,) = struct.unpack_from(">H", data, playlist_start + 6)
        offset = playlist_start + 10
        items: list[tuple[str, int, int]] = []
        for _ in range(item_count):
            (item_length,) = struct.unpack_from(">H", data, offset)
            clip_name = data[offset + 2 : offset + 7].decode("ascii")
            in_time, out_time = struct.unpack_from(">II", data, offset + 14)
            items.append((clip_name, in_time, out_time))
            # the length field does not count itself
            offset += 2 + item_length
    except (struct.error, UnicodeDecodeError) as error:
        raise MplsError("truncated or corrupt MPLS playlist") from error
    return items


def read_playlist(mpls_path: Path, stream_dir: Path | None) -> DiscPlaylist:
    """One playlist, with its clips resolved to the files in `STREAM`."""
    return _build_playlist(
        mpls_path, parse_mpls(mpls_path.read_bytes()), _stream_index(stream_dir)
    )


def _build_playlist(
    mpls_path: Path, entries: list[tuple[str, int, int]], clips: dict[str, Path]
) -> DiscPlaylist:
    items: list[PlaylistItem] = []
    duration = 0.0
    for clip_name, in_time, out_time in entries:
        seconds = max(out_time - in_time, 0) / _TICKS_PER_SECOND
        duration += seconds
        clip = clips.get(clip_name.casefold())
        if clip is None:
            # listed by the playlist but not on disc: nothing to size or play
            continue
        items.append(PlaylistItem(clip, clip.stat().st_size, seconds))
    return DiscPlaylist(
        playlist_id=mpls_path.stem.casefold(),
        path=mpls_path,
        duration=duration,
        items=items,
    )


def read_playlists(playlist_dir: Path, stream_dir: Path | None) -> list[DiscPlaylist]:
    """Every playable playlist on the disc worth offering, in file order.

    Unreadable playlists, loops, clips shorter than a few minutes and exact
    copies of an earlier playlist are left out. If that leaves nothing (a disc
    of shorts), everything that plays at all is offered instead.
    """
    clips = _stream_index(stream_dir)
    playable: list[tuple[DiscPlaylist, list[tuple[str, int, int]]]] = []
    for mpls_path in sorted(
        path for path in playlist_dir.iterdir() if path.suffix.casefold() == ".mpls"
    ):
        try:
            entries = parse_mpls(mpls_path.read_bytes())
            playlist = _build_playlist(mpls_path, entries, clips)
        except (MplsError, OSError):
            continue
        if playlist.items:
            playable.append((playlist, entries))

    seen: set[tuple[tuple[str, int, int], ...]] = set()
    kept: list[DiscPlaylist] = []
    for playlist, entries in playable:
        signature = tuple(entries)
        if signature in seen or _loops(entries):
            continue
        seen.add(signature)
        if (playlist.duration or 0.0) >= MIN_PLAYLIST_SECONDS:
            kept.append(playlist)
    return kept or [playlist for playlist, _ in playable]


def _loops(entries: list[tuple[str, int, int]]) -> bool:
    return any(count > _MAX_REPEATS for count in Counter(entries).values())


def _stream_index(stream_dir: Path | None) -> dict[str, Path]:
    """Clip name (`00001`) to its `.m2ts`, whatever case the disc was ripped in."""
    if stream_dir is None or not stream_dir.is_dir():
        return {}
    return {
        path.stem.casefold(): path
        for path in stream_dir.iterdir()
        if path.suffix.casefold() == ".m2ts"
    }
