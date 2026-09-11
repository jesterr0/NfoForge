"""What moving to the new layout would do, worked out without doing any of it.

Deliberately separate from `src/config/migrations.py`, which migrates the
*contents* of a configuration document through its schema versions. This module
moves directories around and touches no document, and the two must not become
entangled: a layout that has moved says nothing about which schema the files
inside it use, and vice versa.

Planning is a step of its own so that it can be run against a real installation
and shown to someone before anything happens. Nothing here writes, moves or
deletes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re

from src.backend.utils.file_utilities import get_dir_size
from src.backend.utils.frameforge_index_cache import FrameForgeIndexCache
from src.backend.utils.working_dir import JOBS_DIR_NAME, WORKSPACE_DIR_NAME

CACHE_DIR_NAME = "cache"
"""Where derived data that can be rebuilt lives in the new layout."""

PLUGINS_DIR_NAME = "plugins"
"""Where the user's own plugins live, once they stop living beside the release."""

_RUN_FOLDER_STAMP = re.compile(r"_\d{2}\.\d{2}\.\d{4}_\d{2}\.\d{2}\.\d{2}$")
"""The date and time `generate_unique_date_name` appends to a run folder name.

Matching on shape, and only at the end of the name, is what keeps the plan off
anything it did not create. A user's own directory sitting at the root of the
data directory is reported for them to look at, never moved.
"""


class ActionKind(Enum):
    """Whether an entry is relocated within a tree or duplicated into it.

    The distinction is not cosmetic. A move is a rename, which is atomic and
    costs nothing on one volume, and is only available for something already
    inside the destination tree. Anything from outside is copied and its source
    left alone, because that source is an installation the user still has.
    """

    MOVE = "move"
    COPY = "copy"


@dataclass(frozen=True, slots=True)
class PlannedAction:
    kind: ActionKind
    source: Path
    destination: Path
    size: int
    """Bytes, so a summary can say what a step will cost before running it."""


@dataclass(frozen=True, slots=True)
class LegacyInstall:
    """Where a pre-migration installation keeps the things worth importing.

    Resolved by discovery rather than derived here, because the two legacy
    layouts disagree: a release keeps its state under `bundle/runtime` with the
    plugin directory a level above beside the executable, while a source tree
    has `runtime/` and `plugins/` as siblings.
    """

    root: Path
    state: Path
    plugins: Path


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    actions: tuple[PlannedAction, ...]


_LEGACY_ENTRIES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("cookies",), ("cookies",)),
    (("templates",), ("templates",)),
    (("config", "plugins"), ("config", "plugins")),
    (("config", "user"), ("config", "profiles")),
    (("config", "program", "conf.toml"), ("config", "program.toml")),
    (("apps",), ("tools",)),
)
"""Legacy state, as (source, destination) relative to each root.

Three carry a rename. `config/user` becomes `config/profiles` because the new
name says what is in it, `apps` becomes `tools`, and the program preferences
lose the directory that existed to hold one file. Every other entry is a
directory copied whole, so what is nested inside arrives with it -- a profile's
`old_configs` backups have no entry of their own for that reason.
"""


def plan_migration(
    state_root: Path, legacy: LegacyInstall | None = None
) -> MigrationPlan:
    """Everything the move to the new layout would do.

    Relocations inside `state_root` are planned whether or not a legacy
    installation is supplied: saved jobs and run output accumulated at the root
    of the data directory under the old layout regardless of where the
    application itself was installed.
    """
    actions: list[PlannedAction] = []

    jobs = state_root / JOBS_DIR_NAME
    if jobs.is_dir():
        actions.append(
            PlannedAction(
                kind=ActionKind.MOVE,
                source=jobs,
                destination=state_root / WORKSPACE_DIR_NAME / JOBS_DIR_NAME,
                size=get_dir_size(jobs),
            )
        )

    index_cache = state_root / FrameForgeIndexCache.CACHE_DIR_NAME
    if index_cache.is_dir():
        actions.append(
            PlannedAction(
                kind=ActionKind.MOVE,
                source=index_cache,
                destination=state_root
                / CACHE_DIR_NAME
                / FrameForgeIndexCache.CACHE_DIR_NAME,
                size=get_dir_size(index_cache),
            )
        )

    for entry in _children(state_root):
        if not entry.is_dir() or not _RUN_FOLDER_STAMP.search(entry.name):
            continue
        actions.append(
            PlannedAction(
                kind=ActionKind.MOVE,
                source=entry,
                destination=state_root / WORKSPACE_DIR_NAME / entry.name,
                size=get_dir_size(entry),
            )
        )

    if legacy is not None:
        for source_parts, destination_parts in _LEGACY_ENTRIES:
            source = legacy.state.joinpath(*source_parts)
            if not source.exists():
                continue
            actions.append(_copy(source, state_root.joinpath(*destination_parts)))
        if legacy.plugins.is_dir():
            actions.append(_copy(legacy.plugins, state_root / PLUGINS_DIR_NAME))

    return MigrationPlan(actions=tuple(actions))


def _copy(source: Path, destination: Path) -> PlannedAction:
    return PlannedAction(
        kind=ActionKind.COPY,
        source=source,
        destination=destination,
        size=_size(source),
    )


def _size(path: Path) -> int:
    """Bytes at `path`, whether it is a file or a directory."""
    if path.is_file():
        return path.stat().st_size
    return get_dir_size(path)


def _children(directory: Path) -> list[Path]:
    """The direct children of `directory`, sorted, or none if it cannot be read.

    Sorted so a plan is the same on two runs and readable when rendered, and
    tolerant of an unreadable directory because planning runs against a tree
    nobody has verified yet -- reporting nothing there is better than failing
    the whole dry run.
    """
    if not directory.is_dir():
        return []
    try:
        return sorted(directory.iterdir(), key=lambda item: item.name.casefold())
    except OSError:
        return []
