"""Build small disc trees on disk for tests.

The playlists are real MPLS bytes and the title sets real file layouts, so the
parsers under test run for real; only the clips are stubs of a chosen size.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
import struct

TICKS = 45000


def mpls_bytes(items: Sequence[tuple[str, float, float]]) -> bytes:
    """An MPLS playlist playing `(clip name, in seconds, out seconds)` items."""
    body = b""
    for clip, start, end in items:
        item = (
            clip.encode("ascii")
            + b"M2TS"
            + b"\x00\x01"  # flags
            + b"\x00"  # STC id
            + struct.pack(">II", int(start * TICKS), int(end * TICKS))
            + b"\x00" * 12  # the rest of a play item, unread
        )
        body += struct.pack(">H", len(item)) + item
    playlist = struct.pack(">IHHH", len(body) + 6, 0, len(items), 0) + body
    header = b"MPLS0200" + struct.pack(">III", 40, 0, 0) + b"\x00" * 20
    return header + playlist


def make_bluray(
    root: Path,
    playlists: Mapping[str, Sequence[tuple[str, float, float]]],
    clip_sizes: Mapping[str, int],
    *,
    certificate: bool = True,
    upper: bool = True,
) -> Path:
    """A `BDMV` tree under `root`. `upper=False` mimics a lowercase rip."""

    def case(name: str) -> str:
        return name.upper() if upper else name.lower()

    bdmv = root / case("BDMV")
    playlist_dir = bdmv / case("PLAYLIST")
    stream_dir = bdmv / case("STREAM")
    playlist_dir.mkdir(parents=True)
    stream_dir.mkdir()
    if certificate:
        (root / case("CERTIFICATE")).mkdir()
    for clip, size in clip_sizes.items():
        (stream_dir / f"{clip}.{case('m2ts')}").write_bytes(b"\0" * size)
    for name, items in playlists.items():
        (playlist_dir / f"{name}.{case('mpls')}").write_bytes(mpls_bytes(items))
    return root


def make_dvd(
    root: Path,
    title_sets: Mapping[str, Sequence[int]],
    *,
    ifos: bool = True,
    upper: bool = True,
) -> Path:
    """A `VIDEO_TS` tree. `title_sets` maps `"01"` to its VOB sizes, menu first."""

    def case(name: str) -> str:
        return name.upper() if upper else name.lower()

    video_ts = root / case("VIDEO_TS")
    video_ts.mkdir(parents=True)
    (video_ts / case("VIDEO_TS.IFO")).write_bytes(b"\0" * 16)
    for title, sizes in title_sets.items():
        if ifos:
            (video_ts / case(f"VTS_{title}_0.IFO")).write_bytes(b"\0" * 16)
        for part, size in enumerate(sizes):
            (video_ts / case(f"VTS_{title}_{part}.VOB")).write_bytes(b"\0" * size)
    return root
