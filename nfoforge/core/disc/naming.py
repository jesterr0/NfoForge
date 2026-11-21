"""What a disc's name says that a file's name does not.

A full disc is named after the medium, not an encode: its region, its size
class (DVD5/DVD9), PAL or NTSC, and an untouched source. Everything here reads
facts the disc already holds; nothing guesses where it cannot tell.
"""

from __future__ import annotations

from collections.abc import Iterable
import re

from pymediainfo import MediaInfo

from nfoforge.core.disc.model import Disc, DiscType
from nfoforge.enums.rename import QualitySelection

DISC_REGIONS = (
    "USA",
    "CAN",
    "GBR",
    "EUR",
    "GER",
    "FRA",
    "ITA",
    "ESP",
    "NLD",
    "BEL",
    "AUT",
    "SUI",
    "NOR",
    "SWE",
    "DEN",
    "FIN",
    "POL",
    "CZE",
    "HUN",
    "RUS",
    "TUR",
    "AUS",
    "NZL",
    "JPN",
    "KOR",
    "CHN",
    "HKG",
    "TWN",
    "THA",
    "IND",
    "BRA",
    "MEX",
    "ARG",
)
"""Region codes a disc release names, as the trackers that ask for one spell
them. A short list on purpose: a region is only read off a name when it is
unmistakably one, and the user can type any other."""

_SEPARATORS = re.compile(r"[\s._\-()\[\]]+")
_YEAR = re.compile(r"^(19|20)\d{2}$")

DISC_SOURCES = {
    QualitySelection.BLURAY: "Blu-ray",
    QualitySelection.UHD_BLURAY: "UHD Blu-ray",
    QualitySelection.DVD: "DVD",
}
"""How a full disc's source is written: as the medium, "Blu-ray" rather than
the "BluRay" an encode from one is named with."""


def detect_region(disc: Disc, release_name: str) -> str:
    """The region a disc's names state, or "" when none does.

    Read from the release folder's name after its year, where release names
    put it, and from the last word of the disc label (`MOVIE_TITLE_GBR`).
    Never from anywhere a word of the title could sit: "Mad" or "Can" in a
    title is not a region.
    """
    words = [word for word in _SEPARATORS.split(release_name) if word]
    years = [index for index, word in enumerate(words) if _YEAR.match(word)]
    after_year = words[years[-1] + 1 :] if years else []
    label_words = [word for word in _SEPARATORS.split(disc.label) if word]
    candidates: Iterable[str] = [*after_year, *label_words[-1:]]
    for word in candidates:
        if word in DISC_REGIONS:
            return word
    return ""


def dvd_standard(mediainfo: MediaInfo | None) -> str:
    """A DVD's video standard, "PAL" or "NTSC", or "" when it cannot be told.

    MediaInfo states it for most title sets; otherwise the frame height does,
    576 lines being PAL and 480 NTSC.
    """
    if mediainfo is None or not mediainfo.video_tracks:
        return ""
    track = mediainfo.video_tracks[0]
    standard = str(getattr(track, "standard", "") or "").upper()
    if standard in {"PAL", "NTSC"}:
        return standard
    height = str(getattr(track, "height", "") or "")
    return {"576": "PAL", "480": "NTSC"}.get(height, "")


def disc_quality(disc: Disc, mediainfo: MediaInfo | None) -> QualitySelection:
    """The disc's source: DVD, Blu-ray, or UHD Blu-ray above 1080 lines."""
    if disc.disc_type is DiscType.DVD:
        return QualitySelection.DVD
    if disc.bdinfo is not None and any(
        (stream.resolution or "").startswith("2160") for stream in disc.bdinfo.video
    ):
        return QualitySelection.UHD_BLURAY
    if mediainfo is not None and mediainfo.video_tracks:
        height = mediainfo.video_tracks[0].height
        if height and int(height) > 1080:
            return QualitySelection.UHD_BLURAY
    return QualitySelection.BLURAY
