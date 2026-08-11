from collections.abc import Callable
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any
import urllib.parse

from torf import Torrent

from src.backend.utils.subprocess_flags import get_subprocess_creation_flags
from src.exceptions import MkbrrTorrentError, ProcessError
from src.logger.nfo_forge_logger import LOG
from src.payloads.trackers import TrackerInfo
from src.version import __version__, program_name

INDEX_SIDECAR_SUFFIXES = frozenset({".lwi", ".ffindex"})
INDEX_SIDECAR_GLOBS = ("*.lwi", "*.ffindex", "*.LWI", "*.FFINDEX")

BASE_TORRENT_SUFFIX = ".base.torrent"

#: What the torf path writes as ``created by``. mkbrr writes its own string and
#: we keep it, so this value is not universal -- it is only what NfoForge itself
#: stamps, and what a legacy base gets reset to when its inherited value is a
#: tracker's edit rather than a hashing tool's name.
NFO_FORGE_CREATOR = f"{program_name} v{__version__}"


def _validate_torrent_contents(torrent: Torrent) -> None:
    """Ensure private media indexes never become torrent payload files."""
    index_files = [
        str(file)
        for file in torrent.files
        if Path(str(file)).suffix.casefold() in INDEX_SIDECAR_SUFFIXES
    ]
    if index_files:
        raise ValueError(
            "Generated torrent contains excluded index sidecar(s): "
            + ", ".join(index_files)
        )


def content_size(path: Path) -> int:
    """Total bytes the generated torrent will cover.

    Built from torf's own walk with the same `exclude_globs` the torrent uses,
    so the size matches exactly the file set that ends up in it -- a release
    near a piece size band boundary must not be sized from a total that
    includes files the torrent excludes. No hashing happens here; constructing
    the torrent only walks and stats.
    """
    return Torrent(path=path, exclude_globs=INDEX_SIDECAR_GLOBS).size


def generate_torrent(
    path: Path,
    piece_exponent: int,
    cb: Callable[[Torrent, str, int, int], Any],
) -> Torrent:
    """Hash the media into a neutral base torrent.

    Neutral means no announce, source or comment: this torrent belongs to no
    tracker and is never uploaded, so no tracker's server can rewrite it. Every
    tracker -- including the first -- gets a stamped clone of it instead (see
    `clone_torrent`).

    `piece_exponent` is applied verbatim rather than letting torf choose, so
    this fallback produces a torrent shaped identically to the one mkbrr would
    have produced (see `src/backend/torrents/piece_size.py`).
    """
    torrent = Torrent(
        path=path,
        private=True,
        piece_size=2**piece_exponent,
        created_by=NFO_FORGE_CREATOR,
        exclude_globs=INDEX_SIDECAR_GLOBS,
    )
    torrent.generate(callback=cb, interval=0)
    _validate_torrent_contents(torrent)
    return torrent


def neutralize_base(source: Path, destination: Path) -> Path:
    """Copy a carried base torrent to `destination`, stripped of tracker data.

    A base saved with a job before neutral bases existed is a *tracker's*
    artifact -- it was whichever tracker hashed first, and for a UNIT3D tracker
    it is the copy that tracker's server rewrote and handed back. Using it as a
    clone source leaks that tracker's announce, source, comment and `created by`
    into every other tracker's torrent.

    Legacy detection is content-based rather than a schema flag: a neutral base
    has none of these fields by definition, so a base carrying any of them was
    stamped for a tracker. `created_by` is only reset in that case, because on a
    genuinely neutral base it is the hashing tool's name and worth keeping.

    Accepted edge case: a legacy base from a tracker that set no announce,
    source or comment reads as neutral -- but such a torrent carries no tracker
    edit in `created_by` either, so nothing leaks.
    """
    torrent = Torrent.read(source)
    was_stamped = any(
        (
            torrent.metainfo.get("announce"),
            torrent.metainfo.get("announce-list"),
            torrent.metainfo["info"].get("source"),
            torrent.metainfo.get("comment"),
        )
    )
    torrent.private = True
    torrent.metainfo.pop("announce", None)
    torrent.metainfo.pop("announce-list", None)
    torrent.metainfo.pop("comment", None)
    torrent.metainfo["info"].pop("source", None)
    if was_stamped:
        torrent.created_by = NFO_FORGE_CREATOR
    return write_torrent(Torrent.copy(torrent), destination)


def _is_announce_url(value: str) -> bool:
    """Whether torf will accept `value` as an announce URL.

    Mirrors torf's own `is_url` (see `torf/_utils.py`) rather than importing it,
    since that lives in a private module. Matching it matters: a value that
    passes here and fails there would only move the failure later, to the point
    where torf validates on write.
    """
    try:
        parsed = urllib.parse.urlparse(value)
        parsed.port  # noqa: B018 - attribute access is what raises on a bad port
    except Exception:
        return False
    return bool(parsed.scheme and parsed.netloc)


def _shorten(value: str, limit: int = 60) -> str:
    """A one-line, bounded form of a config value, safe to put in an error."""
    collapsed = " ".join(value.split())
    return collapsed if len(collapsed) <= limit else f"{collapsed[:limit]}..."


def clone_torrent(
    tracker_info: TrackerInfo,
    torrent_path: Path,
    base_torrent_file: Path,
    tracker_name: str | None = None,
) -> Torrent:
    """Stamp one tracker's identity onto a copy of the neutral base.

    Every tracker gets one of these, the first included -- no tracker's torrent
    is ever another tracker's clone source. `created_by` is deliberately left
    alone: it names whichever tool hashed the base, and the base is never
    uploaded, so nothing can append an "Edited by" to it.

    `tracker_name` is only used to make a configuration error legible.
    """
    if not base_torrent_file or not base_torrent_file.exists():
        raise FileNotFoundError(f"Cannot find file: {base_torrent_file}")

    # Checked before any file work, and before torf gets the chance to fail on
    # it with a MetainfoError that names neither the tracker nor the setting --
    # and that quotes the offending value in full, which is unreadable when
    # what landed in the field is something like an NFO template.
    if tracker_info.announce_url and not _is_announce_url(tracker_info.announce_url):
        who = f"{tracker_name}: t" if tracker_name else "T"
        where = f" ({tracker_name} -> Announce URL)" if tracker_name else ""
        raise ProcessError(
            f"{who}he configured announce URL is not a valid URL: "
            f"'{_shorten(tracker_info.announce_url)}'. "
            f"Check Settings -> Trackers{where}."
        )

    shutil.copy(base_torrent_file, torrent_path)
    torrent = Torrent.read(torrent_path)
    torrent.private = True
    # Each field is set *or cleared*, never merely overwritten. The base is
    # neutral, so there is normally nothing to clear -- but a tracker that
    # configures no announce, source or comment must end up with none of them
    # rather than inheriting whatever the source torrent happened to carry. A
    # stale comment is visible to anyone who opens the torrent in a client, and
    # a stale source tag changes the infohash; both would advertise the wrong
    # tracker. A tracker with no announce URL wants no announce at all --
    # UNIT3D stamps its own in server-side and returns that torrent on upload.
    if tracker_info.announce_url:
        torrent.metainfo["announce"] = tracker_info.announce_url
    else:
        torrent.metainfo.pop("announce", None)
        torrent.metainfo.pop("announce-list", None)
    if tracker_info.source:
        torrent.metainfo["info"]["source"] = tracker_info.source
    else:
        torrent.metainfo["info"].pop("source", None)
    torrent.comment = tracker_info.comments if tracker_info.comments else None
    clone = Torrent.copy(torrent)
    return clone


def write_torrent(torrent_instance: Torrent, torrent_path: Path) -> Path:
    torrent_instance.write(torrent_path, overwrite=True)
    if not torrent_path.exists():
        raise FileNotFoundError(f"Cannot find file: {torrent_path}")
    return torrent_path


def mkbrr_generate_torrent(
    mkbrr_path: Path,
    path: Path,
    output_path: Path,
    piece_exponent: int,
    cb: Callable[[int], None],
) -> Torrent | None:
    """Hash the media into a neutral base torrent, using mkbrr.

    The torf equivalent is `generate_torrent`; both must produce the same shape,
    which is why the exponent is passed explicitly to each.
    """
    # No --tracker, --source or --comment: the base belongs to no tracker and is
    # never uploaded, so no tracker's server can rewrite it -- `clone_torrent`
    # stamps a per-tracker copy instead. Omitting --tracker also keeps mkbrr's
    # per-tracker piece size rules out of the decision, which matters because
    # they prescribe an exact exponent and conflict between trackers.
    # --output is always explicit, so dropping --tracker cannot change the
    # output filename either (mkbrr only derives a tracker-domain prefix when it
    # picks the name itself).
    #
    # --piece-length sets the exponent exactly. The old --max-piece-length was
    # only a ceiling, which left the real choice to mkbrr and made the torf
    # fallback produce a differently shaped torrent.
    cmd_line = [
        str(mkbrr_path),
        "create",
        str(path),
        "--output",
        str(output_path),
        "--private",
        "--piece-length",
        str(piece_exponent),
    ]
    for pattern in INDEX_SIDECAR_GLOBS:
        cmd_line.extend(("--exclude", pattern))

    LOG.debug(LOG.LOG_SOURCE.BE, f"mkbrr command: {' '.join(cmd_line)}")

    with subprocess.Popen(  # noqa: S603 - list argv, no shell; mkbrr path is the configured binary
        cmd_line,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        creationflags=get_subprocess_creation_flags(new_process_group=True),
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
                torrent = Torrent.read(output_path)
                _validate_torrent_contents(torrent)
                return torrent
            else:
                raise MkbrrTorrentError(f"{result} (code: {return_code})")
        except Exception as e:
            LOG.error(LOG.LOG_SOURCE.BE, f"Error while running mkbrr command ({e}).")
            raise MkbrrTorrentError(
                f"Failed to generate torrent: Unhandled exception {e}"
            ) from e
