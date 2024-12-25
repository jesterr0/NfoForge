import platform

from src.version import program_name, __version__

TRACKER_HEADERS = {
    "User-Agent": f"{program_name} v{__version__} ({platform.system()} {platform.release()})"
}
