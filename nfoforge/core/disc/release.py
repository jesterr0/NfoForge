"""What a tracker is told about a full-disc upload.

Every tracker has to know the same few things about a disc: Blu-ray or DVD,
UHD or not, its size class, and the reports that stand in for MediaInfo.
Deciding them here, once, from the disc itself, is what keeps trackers from
guessing them separately out of the folder name.
"""

from __future__ import annotations

from dataclasses import dataclass

from pymediainfo import MediaInfo

from nfoforge.core.disc.model import Disc, DiscType
from nfoforge.core.disc.naming import disc_quality
from nfoforge.core.disc.size import DiscSize, disc_size_class
from nfoforge.enums.rename import QualitySelection


@dataclass(frozen=True, slots=True)
class DiscRelease:
    """A full disc as trackers see it."""

    disc_type: DiscType
    size_class: DiscSize
    uhd: bool
    bdinfo_summary: str = ""
    """BDInfo's QUICK SUMMARY: what a tracker's BDInfo field takes."""
    ifo_mediainfo: str = ""
    vob_mediainfo: str = ""
    region: str = ""
    distributor: str = ""
    has_certificate: bool | None = None
    image: bool = False
    """Uploaded as one `.iso` file rather than as its folder."""

    @property
    def is_bluray(self) -> bool:
        return self.disc_type is DiscType.BDMV

    @property
    def is_dvd(self) -> bool:
        return self.disc_type is DiscType.DVD


def disc_release(
    disc: Disc,
    mediainfo: MediaInfo | None,
    *,
    region: str = "",
    distributor: str = "",
) -> DiscRelease:
    """The tracker view of `disc`; `mediainfo` is its primary clip's."""
    return DiscRelease(
        disc_type=disc.disc_type,
        size_class=disc_size_class(disc.disc_type, disc.size),
        uhd=disc_quality(disc, mediainfo) is QualitySelection.UHD_BLURAY,
        bdinfo_summary=disc.bdinfo.quick_summary if disc.bdinfo else "",
        ifo_mediainfo=disc.ifo_mediainfo,
        vob_mediainfo=disc.vob_mediainfo,
        region=region.strip(),
        distributor=distributor.strip(),
        has_certificate=disc.has_certificate,
        image=disc.is_image,
    )
