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

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re

from src.backend.utils.file_utilities import get_dir_size
from src.backend.utils.frameforge_index_cache import FrameForgeIndexCache
from src.backend.utils.working_dir import (
    JOBS_DIR_NAME,
    WORKSPACE_DIR_NAME,
    normalise_path,
)

CACHE_DIR_NAME = "cache"
"""Where derived data that can be rebuilt lives in the new layout."""

PLUGINS_DIR_NAME = "plugins"
"""Where the user's own plugins live, once they stop living beside the release."""

TOOLS_DIR_NAME = "tools"
LEGACY_TOOLS_DIR_NAME = "apps"
"""The same directory, before and after. A rename, so both names are needed."""

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
    REWRITE = "rewrite"
    """Repoints a setting. Touches a configuration value, not the filesystem."""


@dataclass(frozen=True, slots=True)
class PlannedAction:
    kind: ActionKind
    source: Path
    destination: Path
    size: int
    """Bytes, so a summary can say what a step will cost before running it.

    Zero for a rewrite, which moves no data.
    """

    detail: str = ""
    """Which setting, for a rewrite. Nothing else needs naming."""


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


class FindingKind(Enum):
    """Something the user is told about rather than something that is done."""

    UNRECOGNISED_ENTRY = "unrecognised-entry"
    """Sits at the root of the data directory and is not part of any layout."""

    PATH_INSIDE_LEGACY_INSTALL = "path-inside-legacy-install"
    """A setting points into the old installation, which the user may delete."""

    RUN_FOLDER_IN_WORKING_DIR = "run-folder-in-working-dir"
    """Reclaimable run output in a directory the user chose. Never swept."""


@dataclass(frozen=True, slots=True)
class Finding:
    kind: FindingKind
    path: Path
    size: int = 0
    detail: str = ""


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    actions: tuple[PlannedAction, ...]
    findings: tuple[Finding, ...] = ()


_KNOWN_ROOT_NAMES = frozenset(
    {
        "layout.json",
        "config",
        "templates",
        "cookies",
        "logs",
        TOOLS_DIR_NAME,
        "migration-conflicts",
        CACHE_DIR_NAME,
        PLUGINS_DIR_NAME,
        WORKSPACE_DIR_NAME,
        JOBS_DIR_NAME,
        FrameForgeIndexCache.CACHE_DIR_NAME,
    }
)
"""Everything the data directory holds, before and after the move.

Anything else at that root came from the user, because the old default working
directory was this directory.
"""


_LEGACY_ENTRIES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("cookies",), ("cookies",)),
    (("templates",), ("templates",)),
    (("config", "plugins"), ("config", "plugins")),
    (("config", "user"), ("config", "profiles")),
    (("config", "program", "conf.toml"), ("config", "program.toml")),
    ((LEGACY_TOOLS_DIR_NAME,), (TOOLS_DIR_NAME,)),
)
"""Legacy state, as (source, destination) relative to each root.

Three carry a rename. `config/user` becomes `config/profiles` because the new
name says what is in it, `apps` becomes `tools`, and the program preferences
lose the directory that existed to hold one file. Every other entry is a
directory copied whole, so what is nested inside arrives with it -- a profile's
`old_configs` backups have no entry of their own for that reason.
"""


def plan_migration(
    state_root: Path,
    legacy: LegacyInstall | None = None,
    configured_paths: Iterable[tuple[str, Path]] = (),
    working_dirs: Iterable[Path] = (),
) -> MigrationPlan:
    """Everything the move to the new layout would do.

    Relocations inside `state_root` are planned whether or not a legacy
    installation is supplied: saved jobs and run output accumulated at the root
    of the data directory under the old layout regardless of where the
    application itself was installed.
    """
    actions: list[PlannedAction] = []
    findings: list[Finding] = []

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
        if entry.is_dir() and _RUN_FOLDER_STAMP.search(entry.name):
            actions.append(
                PlannedAction(
                    kind=ActionKind.MOVE,
                    source=entry,
                    destination=state_root / WORKSPACE_DIR_NAME / entry.name,
                    size=_size(entry),
                )
            )
        elif entry.name.casefold() not in _KNOWN_ROOT_NAMES:
            findings.append(
                Finding(
                    kind=FindingKind.UNRECOGNISED_ENTRY,
                    path=entry,
                    size=_size(entry),
                )
            )

    for working_dir in working_dirs:
        if normalise_path(working_dir) == normalise_path(state_root):
            continue
        for entry in _children(working_dir):
            if entry.is_dir() and _RUN_FOLDER_STAMP.search(entry.name):
                findings.append(
                    Finding(
                        kind=FindingKind.RUN_FOLDER_IN_WORKING_DIR,
                        path=entry,
                        size=_size(entry),
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

        legacy_tools = legacy.state / LEGACY_TOOLS_DIR_NAME
        for label, configured in configured_paths:
            if _is_inside(configured, legacy_tools):
                remainder = normalise_path(configured).relative_to(
                    normalise_path(legacy_tools)
                )
                actions.append(
                    PlannedAction(
                        kind=ActionKind.REWRITE,
                        source=configured,
                        destination=state_root / TOOLS_DIR_NAME / remainder,
                        size=0,
                        detail=label,
                    )
                )
            elif _is_inside(configured, legacy.root):
                findings.append(
                    Finding(
                        kind=FindingKind.PATH_INSIDE_LEGACY_INSTALL,
                        path=configured,
                        detail=label,
                    )
                )

    return MigrationPlan(actions=tuple(actions), findings=tuple(findings))


def _copy(source: Path, destination: Path) -> PlannedAction:
    return PlannedAction(
        kind=ActionKind.COPY,
        source=source,
        destination=destination,
        size=_size(source),
    )


def _is_inside(path: Path, root: Path) -> bool:
    """Whether `path` sits within `root`, comparing what the filesystem means.

    Both sides are normalised first, so a configured path written with a
    different case, a relative segment or a short name is still recognised as
    the same place. `resolve` only recovers real casing for a path that exists,
    but `is_relative_to` compares case-insensitively on Windows anyway, which is
    the platform where that matters.
    """
    return normalise_path(path).is_relative_to(normalise_path(root))


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
