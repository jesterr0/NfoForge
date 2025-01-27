import platform

from src.version import program_name, __version__

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
