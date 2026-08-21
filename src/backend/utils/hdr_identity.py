"""Resolve a release's dynamic range to exactly one identity.

Tracker rules about dynamic range are stated in terms of identity, not
spelling. One tracker drops the assumed HDR10 baseline on a 2160p disc or
remux: HDR10 renders as nothing and DV HDR10 renders as DV, while HDR10+ and
DV HDR10+ are untouched because neither is plain HDR10. Applying that as a
rewrite over an already-rendered string would be inferring identity from how
the string happened to be spelled -- "DV HDR" cannot tell you which of the
two Dolby Vision cases produced it. So identity is resolved here, once, and
spelling happens later and separately.

Deliberately takes no DynamicRangeSettings. Those switches blank the
component by resolution or by type, which is a filename preference: a
tracker rule cannot be subject to a user toggle, and one tracker requires
SDR on a 2160p WEB release from a user who may have SDR switched off.

Pure: no Qt, no config object, no filesystem access.
"""

from __future__ import annotations

from pymediainfo import MediaInfo

from src.config.models import HdrType

_DOLBY_VISION = "Dolby Vision"
_HDR10_PLUS = "HDR10+"
_HDR10 = "HDR10"

# Dolby Vision profile 5 carries an IPT base layer that nothing but a DV
# decoder can display, so there is no HDR10 to fall back to. Every other
# profile a release ships in is HDR10-compatible, whether or not MediaInfo
# appends the "HDR10 compatible" half of the string.
_DV_NO_BASE_LAYER = "dvhe.05"


def resolve_hdr_identity(media_info: MediaInfo | None) -> HdrType:
    """The one dynamic range identity a release has.

    SDR is the absence of an HDR signal rather than a signal of its own, so
    unreadable media answers SDR instead of raising or returning unknown --
    a release title needs a value, and "no HDR was found" is the honest one.
    """
    hdr_format = ""
    transfer_characteristics = ""

    if media_info and media_info.video_tracks:
        # `other_hdr_format` holds the human-readable form; MediaInfo emits
        # HDR_Format more than once and pymediainfo keeps the first
        # occurrence in `hdr_format` and the rest here. Missing, empty or
        # None all mean "no HDR format reported", hence the wide guard.
        try:
            hdr_format = media_info.video_tracks[0].other_hdr_format[0]
        except (AttributeError, IndexError, TypeError):
            pass
        try:
            transfer_characteristics = media_info.video_tracks[
                0
            ].transfer_characteristics
        except (AttributeError, IndexError, TypeError):
            pass

    if hdr_format:
        # HDR10+ is tested before HDR10 throughout because it contains it as
        # a substring. Getting this backwards would collapse HDR10+ into the
        # baseline the tracker rule strips.
        if _DOLBY_VISION in hdr_format:
            if _HDR10_PLUS in hdr_format:
                return "DV HDR10+"
            if _DV_NO_BASE_LAYER in hdr_format:
                return "DV"
            return "DV HDR10"
        if _HDR10_PLUS in hdr_format:
            return "HDR10+"
        if _HDR10 in hdr_format:
            return "HDR10"

    # Reached either with no HDR format at all or with one that names no
    # format NfoForge knows (a bare mastering-display tag, say). The
    # transfer function is the weaker claim and the right one to fall back
    # on: it says the file is PQ or HLG without asserting a metadata format.
    if transfer_characteristics == "PQ":
        return "PQ"
    if transfer_characteristics == "HLG":
        return "HLG"
    return "SDR"
