import shutil
from collections.abc import Callable
from os import PathLike
from pathlib import Path
from torf import Torrent

from src.version import __version__, program_name
from src.payloads.trackers import TrackerInfo


def generate_torrent(
    tracker_info: TrackerInfo,
    input_file: Path,
    max_piece_size: int | None,
    cb: Callable[[Torrent, PathLike[str], int, int], None],
) -> Torrent:
    torrent = Torrent(
        path=input_file,
        trackers=tracker_info.announce_url,
        private=True,
        source=tracker_info.source if tracker_info.source else None,
        comment=tracker_info.comments if tracker_info.comments else None,
        piece_size_max=max_piece_size,
        created_by=f"{program_name} v{__version__}",
    )
    torrent.generate(callback=cb, interval=0)
    return torrent


def clone_torrent(
    tracker_info: TrackerInfo,
    torrent_path: Path,
    base_torrent_file: Path,
) -> Torrent:
    if not base_torrent_file or not base_torrent_file.exists():
        raise FileNotFoundError(f"Cannot find file: {base_torrent_file}")

    shutil.copy(base_torrent_file, torrent_path)
    torrent = Torrent.read(torrent_path)
    torrent.metainfo["announce"] = tracker_info.announce_url
    torrent.private = True
    torrent.metainfo["info"]["source"] = tracker_info.source
    torrent.comment = tracker_info.comments if tracker_info.comments else None
    clone = Torrent.copy(torrent)
    return clone


def write_torrent(torrent_instance: Torrent, torrent_path: Path) -> Path:
    torrent_instance.write(torrent_path, overwrite=True)
    if not torrent_path.exists():
        raise FileNotFoundError(f"Cannot find file: {torrent_path}")
    return torrent_path
