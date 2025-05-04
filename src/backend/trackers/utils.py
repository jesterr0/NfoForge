import platform

from src.version import program_name, __version__
from src.enums.tracker_selection import TrackerSelection

TRACKER_HEADERS = {
    "User-Agent": f"{program_name} v{__version__} ({platform.system()} {platform.release()})"
}


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
    TrackerSelection.MORE_THAN_TV: _basic_bbcode_formatting,
    # TrackerSelection.TORRENT_LEECH: "", # doesn't support image resizing
    TrackerSelection.BEYOND_HD: _beyond_hd_formatting,
    # TrackerSelection.PASS_THE_POPCORN: "", # doesn't support image resizing
    TrackerSelection.REELFLIX: _basic_bbcode_formatting,
    TrackerSelection.AITHER: _basic_bbcode_formatting,
    TrackerSelection.LST: _basic_bbcode_formatting,
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
