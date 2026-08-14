from collections.abc import Mapping
import platform
import re

import flatbencode as bencode
from niquests.structures import CaseInsensitiveDict
import regex

from src.enums.tracker_selection import TrackerSelection
from src.logger.nfo_forge_logger import LOG
from src.version import __version__, program_name

TRACKER_HEADERS = {
    "User-Agent": f"{program_name} v{__version__} ({platform.system()} {platform.release()})"
}

# JSON API requests must explicitly advertise the representation they expect.
# Do not add this to TRACKER_HEADERS: several trackers upload through ordinary
# browser-style forms and legitimately return HTML or plain text.
API_TRACKER_HEADERS = {**TRACKER_HEADERS, "Accept": "application/json"}

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


# Audio channel layout -- 1.0, 2.0, 2.1 ... 7.1, 8.1, plus Atmos-style height
# groups such as 7.1.4. Matched by shape rather than against an enumerated list of
# codecs and layouts, so a codec or layout the audio conventions gain later is
# covered for free: a digit 1-9, the LFE digit (only ever 0 or 1), and no digit on
# either outer side, so a year/resolution boundary such as "2019.1080p" is never
# mistaken for a layout. A true decimal like "9.5 Weeks" is likewise left alone --
# .5 is not an LFE digit.
_CHANNEL_LAYOUT_REGEX = re.compile(r"(?<!\d)[1-9]\.[01](?:\.[0-9])?(?!\d)")
_CHANNEL_LAYOUT_SENTINEL = "\x00"
_REPEATED_WHITESPACE_REGEX = re.compile(r"\s{2,}")
_REPEATED_PERIOD_REGEX = re.compile(r"\.{2,}")


def strip_title_dots(release_title: str) -> str:
    """
    Convert a dot separated release title into a space separated one, keeping
    audio channel layouts (2.0, 5.1, 7.1.4, ...) intact.

    The channel layout is protected before the periods are stripped rather than
    reconstructed afterwards. Reconstruction requires knowing every codec that can
    precede the channels, and anything the list missed (AAC, Opus, LPCM, an Atmos
    suffix between the codec and the channels, ...) silently shipped as "5 1".
    """
    name = _CHANNEL_LAYOUT_REGEX.sub(
        lambda match: match.group(0).replace(".", _CHANNEL_LAYOUT_SENTINEL),
        release_title,
    )
    name = name.replace(".", " ")
    name = _REPEATED_WHITESPACE_REGEX.sub(" ", name)
    return name.replace(_CHANNEL_LAYOUT_SENTINEL, ".")


def dot_separate_title(release_title: str) -> str:
    """
    Convert a space separated release title into a dot separated one.

    The inverse of `strip_title_dots`, for trackers that name uploads after the
    release itself rather than in prose. No channel-layout protection is needed
    going this way: only spaces become periods, so a layout that is already
    "5.1" simply passes through.

    Idempotent, so a title that arrives dot separated -- the filename fallback,
    which is the release name already -- is returned unchanged instead of being
    round-tripped through the spaced form.
    """
    name = _REPEATED_WHITESPACE_REGEX.sub(" ", release_title.strip())
    name = name.replace(" ", ".")
    name = _REPEATED_PERIOD_REGEX.sub(".", name)
    return name.strip(".")


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
