"""Produce the reports a disc upload carries.

A Blu-ray is described by a BDInfo scan of its selected playlist. A DVD is
described by MediaInfo of its title set's IFO (languages, runtime) and of the
first feature VOB (the streams themselves); trackers want both.
"""

from __future__ import annotations

from pathlib import Path

from nfoforge.backend.utils.media_info_utils import MinimalMediaInfo
from nfoforge.core.disc.bdinfo import (
    BDInfoError,
    BdinfoRsScanner,
    BDInfoScanner,
    ProgressCallback,
)
from nfoforge.core.disc.bdinfo_report import (
    BDInfoReport,
    BDInfoReportError,
    parse_bdinfo_report,
)
from nfoforge.core.disc.model import Disc, DiscType, normalize_playlist_id

MISSING_BDINFO = (
    "A full Blu-ray upload needs a BDInfo report, and no BDInfo (bdinfo-rs) "
    "path is set. Set it under Settings -> Dependencies."
)


def describe_disc(
    disc: Disc,
    bdinfo_path: Path | None,
    report_dir: Path,
    progress: ProgressCallback | None = None,
    scanner: BDInfoScanner | None = None,
) -> None:
    """Fill in `disc`'s reports for its selected playlist.

    Raises `BDInfoError` when a Blu-ray cannot be scanned. A report already in
    `report_dir` for the same playlist is reused rather than scanned again.
    """
    selected = disc.selected_playlists()
    if not selected:
        raise BDInfoError(f"No playlist is selected on {disc.label}")
    playlist = selected[0]

    if disc.disc_type is DiscType.DVD:
        if playlist.path is not None:
            disc.ifo_mediainfo = _mediainfo_text(playlist.path)
        vob = disc.primary_media_file()
        if vob is not None:
            disc.vob_mediainfo = _mediainfo_text(vob)
        return

    cached = cached_bdinfo_report(report_dir, playlist.playlist_id)
    if cached is not None:
        disc.bdinfo = cached
        return
    if scanner is None:
        if bdinfo_path is None:
            raise BDInfoError(MISSING_BDINFO)
        scanner = BdinfoRsScanner(bdinfo_path)
    disc.bdinfo = scanner.scan(disc, playlist.playlist_id, report_dir, progress)


def cached_bdinfo_report(report_dir: Path, playlist_id: str) -> BDInfoReport | None:
    """A report in `report_dir` that covers `playlist_id`, if there is one."""
    if not report_dir.is_dir():
        return None
    wanted = normalize_playlist_id(playlist_id)
    for path in sorted(report_dir.glob("*.txt")):
        if not path.name.casefold().startswith("bdinfo"):
            continue
        try:
            report = parse_bdinfo_report(
                path.read_text(encoding="utf-8", errors="replace")
            )
        except (BDInfoReportError, OSError):
            continue
        if normalize_playlist_id(report.playlist) == wanted:
            return report
    return None


def _mediainfo_text(path: Path) -> str:
    """MediaInfo's text for `path`, naming the file but not where it lives."""
    try:
        return MinimalMediaInfo(path).get_full_mi_str(cleansed=True)
    except Exception:
        # a title set MediaInfo cannot read leaves that report empty; the
        # tracker payload decides whether an upload can go without it
        return ""
