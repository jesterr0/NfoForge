"""Which files in a release folder are episodes, and which merely follow one.

Opening a directory pulls in whatever happens to be sitting in it. Two
different questions have to be answered about that content, and both are asked
from more than one place, so they live here rather than in any one caller:

- Is this file a release's *media*? `MediaInputPayload.file_list` is consumed by
  MediaInfo parsing, the series episode mapper and the `{episode_mediainfo}` /
  `{episode_metadata}` tokens, none of which have anything to say about a
  subtitle or an `.nfo`.
- Does this file *belong to* one of those media files? A subtitle named after
  its episode has to keep being named after it once the episode is renamed,
  or the pair silently comes apart.

Deliberately free of Qt imports so the rename backend and its tests can use it.
"""

from __future__ import annotations

from collections.abc import Container, Iterable
from os import scandir
from pathlib import Path
import re

# Shared with `MediaTitleInferer`, which reads them off this module. Anything
# a release ships as its actual content; containers only, since a file that
# cannot hold video is never the thing being uploaded.
VIDEO_EXTENSIONS = frozenset(
    {
        ".3gp",
        ".avi",
        ".divx",
        ".flv",
        ".iso",
        ".m2ts",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".mts",
        ".ogm",
        ".ogv",
        ".rm",
        ".rmvb",
        ".ts",
        ".vob",
        ".webm",
        ".wmv",
    }
)

#: "sample" as a whole separator-delimited word, so `Show.S01E01.sample.mkv`
#: and `sample-Show.mkv` are excluded while `Show.Sampler.S01E01.mkv` is not.
SAMPLE_PATTERN = re.compile(r"(?:^|[._\-\s])sample(?:$|[._\-\s])", re.IGNORECASE)

#: What may join a media file's stem to the rest of a sidecar's name. A bare
#: concatenation is intentionally not accepted: `ep01a.mkv` must not be read as
#: a sidecar of `ep01.mkv`.
_SIDECAR_SEPARATORS = (".", "-", "_")


def is_media_file(path: Path) -> bool:
    """Whether `path` is release media rather than an extra sitting beside it."""
    return path.suffix.casefold() in VIDEO_EXTENSIONS and not is_sample(path)


def is_sample(path: Path) -> bool:
    """Whether `path` is a sample clip rather than the release itself."""
    return bool(SAMPLE_PATTERN.search(path.stem))


def filter_media_files(paths: Iterable[Path]) -> list[Path]:
    """`paths` reduced to release media, order preserved."""
    return [path for path in paths if is_media_file(path)]


def sidecar_suffix(media_file: Path, candidate: Path) -> str | None:
    """The part of `candidate`'s name that follows `media_file`'s stem.

    Returns ``None`` when `candidate` does not belong to `media_file`. The
    returned text includes its leading separator (".en.srt", "-eng.sub"), which
    is what makes a rename a pure stem swap: the new name is the episode's new
    stem plus this text verbatim, so a language tag or an ordering suffix
    survives untouched.
    """
    stem = media_file.stem
    name = candidate.name
    if len(name) <= len(stem) or not name[: len(stem)].casefold() == stem.casefold():
        return None
    remainder = name[len(stem) :]
    if not remainder.startswith(_SIDECAR_SEPARATORS):
        return None
    return remainder


def find_sidecars(
    media_file: Path,
    *,
    exclude: Container[Path] = frozenset(),
) -> dict[Path, str]:
    """Files beside `media_file` that are named after it, mapped to their suffix.

    `exclude` is the rest of the release's media, so that in a folder holding
    both `ep01.mkv` and `ep01.mp4` neither is treated as the other's sidecar.
    A directory is never a sidecar -- an `Extras` folder is moved by its parent
    being renamed, not by being renamed itself.

    Prefer `find_sidecars_for` for a whole release: this scans the directory on
    every call, which a per-episode loop over one folder repeats needlessly.
    """
    return _match_sidecars(media_file, _list_files(media_file.parent), exclude)


def find_sidecars_for(
    media_files: Iterable[Path],
) -> dict[Path, dict[Path, str]]:
    """`find_sidecars` for a whole release, reading each directory once.

    A pack can hold hundreds of episodes in one folder, and every one of them
    has the same siblings; scanning per episode turns that into a quadratic
    pile of stat calls on what may well be a network share.

    Every media file passed in is excluded from every other's sidecars, so a
    release shipping both `ep01.mkv` and `ep01.mp4` does not have one adopt the
    other.
    """
    media_files = list(media_files)
    media_set = frozenset(media_files)
    listings: dict[Path, list[Path]] = {}
    for media_file in media_files:
        parent = media_file.parent
        if parent not in listings:
            listings[parent] = _list_files(parent)
    return {
        media_file: _match_sidecars(media_file, listings[media_file.parent], media_set)
        for media_file in media_files
    }


def _list_files(directory: Path) -> list[Path]:
    """Regular files directly in `directory`, or empty if it cannot be read.

    `os.scandir` rather than `Path.iterdir` + `is_dir`: the directory read
    already carries the entry type on every platform this runs on, so this
    costs one syscall for the whole listing instead of one stat per entry.
    """
    try:
        with scandir(directory) as entries:
            return sorted(Path(entry.path) for entry in entries if not entry.is_dir())
    except OSError:
        return []


def _match_sidecars(
    media_file: Path,
    candidates: Iterable[Path],
    exclude: Container[Path],
) -> dict[Path, str]:
    sidecars: dict[Path, str] = {}
    for candidate in candidates:
        if candidate == media_file or candidate in exclude:
            continue
        suffix = sidecar_suffix(media_file, candidate)
        if suffix is not None:
            sidecars[candidate] = suffix
    return sidecars
