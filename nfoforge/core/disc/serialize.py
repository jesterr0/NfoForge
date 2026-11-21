"""A disc as plain JSON, for saved jobs.

The reports are stored whole, as text: a job is resumed after the disc may be
gone, and the report is what the trackers are sent. A Blu-ray's structured
report is re-read from that text rather than stored field by field, so the
parser stays the only thing that knows its layout.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nfoforge.core.disc.bdinfo_report import BDInfoReportError, parse_bdinfo_report
from nfoforge.core.disc.model import Disc, DiscPlaylist, DiscType, PlaylistItem


def disc_to_dict(disc: Disc) -> dict[str, Any]:
    return {
        "root": str(disc.root),
        "image": str(disc.image) if disc.image else None,
        "disc_type": str(disc.disc_type),
        "label": disc.label,
        "size": disc.size,
        "has_certificate": disc.has_certificate,
        "selected": list(disc.selected),
        "playlists": [
            {
                "playlist_id": playlist.playlist_id,
                "path": str(playlist.path) if playlist.path else None,
                "duration": playlist.duration,
                "is_main": playlist.is_main,
                "items": [
                    {
                        "path": str(item.path),
                        "size": item.size,
                        "duration": item.duration,
                    }
                    for item in playlist.items
                ],
            }
            for playlist in disc.playlists
        ],
        "bdinfo": disc.bdinfo.full if disc.bdinfo else None,
        "ifo_mediainfo": disc.ifo_mediainfo,
        "vob_mediainfo": disc.vob_mediainfo,
    }


def disc_from_dict(document: Any) -> Disc | None:
    """The disc `disc_to_dict` wrote, or None for anything else."""
    if not isinstance(document, Mapping):
        return None
    try:
        disc = Disc(
            root=Path(document["root"]),
            disc_type=DiscType(document["disc_type"]),
            label=str(document.get("label") or ""),
            size=int(document.get("size") or 0),
            playlists=[
                _playlist(entry)
                for entry in document.get("playlists") or ()
                if isinstance(entry, Mapping)
            ],
            selected=[str(entry) for entry in document.get("selected") or ()],
            ifo_mediainfo=str(document.get("ifo_mediainfo") or ""),
            vob_mediainfo=str(document.get("vob_mediainfo") or ""),
        )
    except (KeyError, TypeError, ValueError):
        return None
    image = document.get("image")
    # the root is where the image was mounted then; it is mounted again,
    # wherever the system puts it, before anything inside is read
    disc.image = Path(image) if isinstance(image, str) and image else None
    certificate = document.get("has_certificate")
    disc.has_certificate = certificate if isinstance(certificate, bool) else None
    report = document.get("bdinfo")
    if isinstance(report, str) and report.strip():
        try:
            disc.bdinfo = parse_bdinfo_report(report)
        except BDInfoReportError:
            disc.bdinfo = None
    return disc


def _playlist(document: Mapping[str, Any]) -> DiscPlaylist:
    path = document.get("path")
    return DiscPlaylist(
        playlist_id=str(document["playlist_id"]),
        path=Path(path) if isinstance(path, str) and path else None,
        duration=_seconds(document.get("duration")),
        items=[
            PlaylistItem(
                path=Path(item["path"]),
                size=int(item.get("size") or 0),
                duration=_seconds(item.get("duration")),
            )
            for item in document.get("items") or ()
            if isinstance(item, Mapping)
        ],
        is_main=bool(document.get("is_main")),
    )


def _seconds(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
