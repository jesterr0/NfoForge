from collections.abc import Mapping
import platform

import flatbencode as bencode
from niquests.structures import CaseInsensitiveDict
import regex

from src.enums.tracker_selection import TrackerSelection
from src.logger.nfo_forge_logger import LOG
from src.version import __version__, program_name

TRACKER_HEADERS = {
    "User-Agent": f"{program_name} v{__version__} ({platform.system()} {platform.release()})"
}

# Shared disc-detection heuristic used by every tracker that infers a
# release's disc/encode/remux type from its filename (BeyondHD, the UNIT3D
# family, PassThePopcorn, HDBits). Compiled case-insensitively: its literal
# tokens (AVC, HEVC, BD, Blu, ISO, COMPLETE, ...) are upper/mixed-case, but
# every caller matches it against an already-lowercased title -- without
# IGNORECASE the positive-match branches can never fire, so a real disc
# release always fell through to whatever check came next (silently
# misclassified as an encode, or -- for the UNIT3D trackers -- rejected
# outright with "Failed to determine 'Type ID'"). One shared, correctly
# case-insensitive pattern instead of four independently-drifting copies.
DISC_TITLE_REGEX = regex.compile(
    (
        r"^(?!.*\b((?<!HD[._ -]|HD)DVD|BDRip|720p|MKV|XviD"
        r"|WMV|d3g|(BD)?REMUX|^(?=.*1080p)(?=.*HEVC)|[xh][-_. ]"
        r"?26[45]|German.*[DM]L|((?<=\d{4}).*German.*([DM]L)?)"
        r"(?=.*\b(AVC|HEVC|VC[-_. ]?1|MVC|MPEG[-_. ]?2)\b))\b)(((?=.*\b(Blu[-_. ]?ray"
        r"|BD|HD[-_. ]?DVD)\b)(?=.*\b(AVC|HEVC|VC[-_. ]?1|MVC|"
        r"MPEG[-_. ]?2|BDMV|ISO)\b))|^((?=.*\b(((?=.*\b((.*_)?COMPLETE.*"
        r"|Dis[ck])\b)(?=.*(Blu[-_. ]?ray|HD[-_. ]?DVD)))|3D[-_. ]?BD|"
        r"BR[-_. ]?DISK|Full[-_. ]?Blu[-_. ]?ray|^((?=.*((BD|UHD)[-_. ]?(25"
        r"|50|66|100|ISO)))))))).*"
    ),
    regex.IGNORECASE,
)


def tracker_string_replace_map() -> dict[str, str]:
    # audio codecs
    codec_s = (
        "DD",
        "DD-EX",
        "DD+",
        "DDP",
        "TrueHD",
        "DTS",
        "DTS-ES",
        "DTS-HD MA",
        "DTS-HD HRA",
        "DTS:X",
        "FLAC",
    )
    channel_s = (
        "1.0",
        "2.0",
        "2.1",
        "3.0",
        "3.1",
        "4.0",
        "4.1",
        "5.0",
        "5.1",
        "6.1",
        "7.1",
    )
    str_replace_map = {}
    for codec in codec_s:
        for channel in channel_s:
            str_replace_map[f"{codec} {channel.replace('.', ' ')}"] = (
                f"{codec} {channel}"
            )

    return str_replace_map


def _basic_bbcode_formatting(url: str, image_size: int) -> str:
    return url.replace("[img]", f"[img={image_size}]")


def _beyond_hd_formatting(url: str, image_size: int) -> str:
    return url.replace("[img]", f"[img width={image_size}]")


_TRACKER_MAP = {
    # TrackerSelection.TORRENT_LEECH: "", # doesn't support image resizing
    TrackerSelection.BEYOND_HD: _beyond_hd_formatting,
    # TrackerSelection.PASS_THE_POPCORN: "", # doesn't support image resizing
    TrackerSelection.REELFLIX: _basic_bbcode_formatting,
    TrackerSelection.AITHER: _basic_bbcode_formatting,
    TrackerSelection.LST: _basic_bbcode_formatting,
    TrackerSelection.DARK_PEERS: _basic_bbcode_formatting,
    TrackerSelection.SHARE_ISLAND: _basic_bbcode_formatting,
    TrackerSelection.UPLOAD_CX: _basic_bbcode_formatting,
    TrackerSelection.ONLY_ENCODES: _basic_bbcode_formatting,
    TrackerSelection.HDB: _basic_bbcode_formatting,
    TrackerSelection.BLUTOPIA: _basic_bbcode_formatting,
    TrackerSelection.SEEDPOOL: _basic_bbcode_formatting,
    TrackerSelection.UTOPIA: _basic_bbcode_formatting,
    TrackerSelection.YU_SCENE: _basic_bbcode_formatting,
    TrackerSelection.FEAR_NO_PEER: _basic_bbcode_formatting,
}


def format_image_tag(
    tracker: TrackerSelection, url_str: str, image_size: int = 350
) -> str:
    """
    Formats an image tag based on tracker-specific requirements.

    Args:
        tracker (TrackerSelection): The tracker that requires special formatting.
        url_str (str): The input URL string containing an image tag.
        image_size (int): Image size to set for the tags.

    Returns:
        str: The formatted URL string with the correct image tag size.
    """
    return (
        _TRACKER_MAP[tracker](url_str, image_size)
        if tracker in _TRACKER_MAP
        else url_str
    )


def looks_like_torrent(
    content: bytes,
    headers: Mapping[str, str] | CaseInsensitiveDict[str] | None = None,
) -> bool:
    """Return True if response content (and optional headers) look like a .torrent."""
    if not content:
        return False

    # fast header check
    ctype = str((headers or {}).get("Content-Type", "")).lower()
    if "application/x-bittorrent" in ctype:
        return True

    # prefer flatbencode.decode
    try:
        bencode.decode(content)
        return True
    except Exception as error:
        # not valid bencode — expected for most non-torrent responses, so
        # fall back to heuristics; logged at debug level since this is a
        # routine, not exceptional, path
        LOG.debug(
            LOG.LOG_SOURCE.BE,
            f"Content is not valid bencode, falling back to heuristics: {error}",
        )

    # heuristic checks (preferred over just searching for 'd8:announce')
    if content.startswith(b"d") and b"announce" in content[:500]:
        return True

    # last-resort: look for common token
    if b"d8:announce" in content[:200]:
        return True

    return False
