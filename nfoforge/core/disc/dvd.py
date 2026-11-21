"""Read a DVD's title sets.

Each `VTS_nn` set is one title: an `.IFO` describing it, a menu VOB (`_0`) and
the feature split across `_1`, `_2`, ... VOBs. Only the feature VOBs are a
title set's items. The main feature is found by
size, because that is always known; runtime is read from the IFO when it can be
and is only ever used to show the user and to spot alternate cuts.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import re

from nfoforge.core.disc.model import DiscPlaylist, PlaylistItem, is_menu_vob

_VTS_FILE = re.compile(r"^vts_(\d{2})_(\d+)\.(vob|ifo)$", re.IGNORECASE)

MIN_TITLE_SECONDS = 180.0

DurationReader = Callable[[Path], float | None]


def ifo_duration(ifo_path: Path) -> float | None:
    """A title set's runtime in seconds, or ``None`` when it cannot be read."""
    try:
        from pymediainfo import MediaInfo

        media_info = MediaInfo.parse(ifo_path, legacy_stream_display=True)
        if not isinstance(media_info, MediaInfo):
            return None
        for track in media_info.general_tracks:
            if track.duration:
                return float(track.duration) / 1000.0
    except Exception:
        # an unreadable IFO costs the runtime column, not the upload
        return None
    return None


def read_title_sets(
    video_ts: Path, duration_reader: DurationReader = ifo_duration
) -> list[DiscPlaylist]:
    """The disc's title sets that hold a feature, in title order."""
    vobs: dict[str, list[tuple[int, Path]]] = {}
    ifos: dict[str, Path] = {}
    for path in video_ts.iterdir():
        match = _VTS_FILE.match(path.name)
        if not match or not path.is_file():
            continue
        title, part, kind = match.group(1), int(match.group(2)), match.group(3)
        if kind.casefold() == "ifo":
            if part == 0:
                ifos[title] = path
        else:
            vobs.setdefault(title, []).append((part, path))

    title_sets: list[DiscPlaylist] = []
    for title in sorted(vobs):
        # the menu VOB is not the feature: counting it lets a title with an
        # elaborate menu outweigh a longer one
        parts = [path for _, path in sorted(vobs[title]) if not is_menu_vob(path)]
        if not parts:
            continue
        ifo = ifos.get(title)
        title_sets.append(
            DiscPlaylist(
                playlist_id=title,
                path=ifo,
                duration=duration_reader(ifo) if ifo else None,
                items=[PlaylistItem(path, path.stat().st_size) for path in parts],
            )
        )

    # a runtime that could not be read is not evidence the title is short
    kept = [
        title_set
        for title_set in title_sets
        if title_set.duration is None or title_set.duration >= MIN_TITLE_SECONDS
    ]
    return kept or title_sets
