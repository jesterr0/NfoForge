from collections.abc import Callable
import math
from pathlib import Path
import platform
import re
import shutil
import subprocess
from typing import Any

from torf import Torrent

from src.exceptions import MkbrrTorrentError
from src.logger.nfo_forge_logger import LOG
from src.payloads.trackers import TrackerInfo
from src.version import __version__, program_name


def generate_torrent(
    tracker_info: TrackerInfo,
    path: Path,
    max_piece_size: int | None,
    cb: Callable[[Torrent, str, int, int], Any],
) -> Torrent:
    torrent = Torrent(
        path=path,
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
    torrent.private = True
    if tracker_info.announce_url:
        torrent.metainfo["announce"] = tracker_info.announce_url
    if tracker_info.source:
        torrent.metainfo["info"]["source"] = tracker_info.source
    if tracker_info.comments:
        torrent.comment = tracker_info.comments
    clone = Torrent.copy(torrent)
    return clone


def write_torrent(torrent_instance: Torrent, torrent_path: Path) -> Path:
    torrent_instance.write(torrent_path, overwrite=True)
    if not torrent_path.exists():
        raise FileNotFoundError(f"Cannot find file: {torrent_path}")
    return torrent_path


def _bytes_to_mkbrr_exponent(size_bytes: int) -> int:
    """Helper function to convert bytes to mkbrr exponent"""

    min_exp, max_exp = 16, 27
    n = math.ceil(math.log2(size_bytes))
    n = max(min_exp, min(n, max_exp))
    if not (min_exp <= n <= max_exp):
        raise ValueError("Piece size exponent out of mkbrr range")
    return n


def mkbrr_generate_torrent(
    mkbrr_path: Path,
    tracker_info: TrackerInfo,
    path: Path,
    output_path: Path,
    max_piece_size: int | None,
    cb: Callable[[int], None],
) -> Torrent | None:
    cmd_line = [
        str(mkbrr_path),
        "create",
        str(path),
        "--output",
        str(output_path),
        "--private",
        "--tracker",
        tracker_info.announce_url,
    ]
    if max_piece_size:
        cmd_line.extend(
            ("--max-piece-length", str(_bytes_to_mkbrr_exponent(max_piece_size)))
        )
    if tracker_info.source:
        cmd_line.extend(("--source", tracker_info.source))
    if tracker_info.comments:
        cmd_line.extend(("--comment", tracker_info.comments))

    LOG.debug(LOG.LOG_SOURCE.BE, f"mkbrr command: {' '.join(cmd_line)}")

    with subprocess.Popen(
        cmd_line,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        if platform.system() == "Windows"
        else 0,
    ) as job:
        try:
            result = None
            if job.stdout:
                for line in job.stdout:
                    match = re.search(r"\s(\d+)%", line.strip())
                    if match:
                        progress = int(match.group(1))
                        cb(progress)
                    if "Wrote" in line:
                        result = True
                    if "Error" in line:
                        result = line

            if job.stdout:
                job.stdout.close()

            job.wait()
            return_code = job.returncode
            if result is True and return_code == 0:
                return Torrent.read(output_path)
            else:
                raise MkbrrTorrentError(f"{result} (code: {return_code})")
        except Exception as e:
            LOG.error(LOG.LOG_SOURCE.BE, f"Error while running mkbrr command ({e}).")
            raise MkbrrTorrentError(
                f"Failed to generate torrent: Unhandled exception {e}"
            )
