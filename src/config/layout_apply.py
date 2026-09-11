"""Carrying out a migration plan. The only module here that can lose data.

Written under one rule, which a test enforces against this file: nothing in it
may delete. Moves are renames, copies leave their source alone, and there is no
call anywhere that removes a file or a directory. A migration that cannot delete
cannot destroy someone's data, however wrong the rest of it turns out to be.

The cost is accepted deliberately. A run that fails part way leaves a partial
copy behind for the user to remove, and leaving litter is a better failure than
clearing a directory that turned out to hold something else.

The plan is the input and nothing is recomputed here. What the user reads before
agreeing is exactly what runs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
import shutil

from src.config.layout_migration import ActionKind, MigrationPlan
from src.config.layout_version import (
    pending_hops,
    read_layout_version,
    write_layout_version,
)

CONFLICTS_DIR_NAME = "migration-conflicts"
"""Where something goes when its destination is already occupied."""


class MigrationError(Exception):
    """A step did not do what it claimed, so the run stops and says so."""


@dataclass(frozen=True, slots=True)
class Diversion:
    """Something that could not go where it was planned to."""

    planned: Path
    actual: Path


@dataclass(frozen=True, slots=True)
class MigrationOutcome:
    diverted: tuple[Diversion, ...] = ()


def migrate_layout(plan: MigrationPlan) -> MigrationOutcome:
    """Run whichever hops `plan`'s data directory still needs, in order.

    The recorded version decides, not the plan. A plan is built before the user
    is asked anything, so by the time one is applied the tree may already have
    been migrated -- by a previous run, or by another copy of the application.
    Replaying it would move an already-moved tree.

    The version is written after each hop rather than once at the end, so a run
    interrupted part way resumes from where it stopped. Nothing is written
    before the work it describes has happened.
    """
    pending = pending_hops(read_layout_version(plan.state_root))
    outcome = MigrationOutcome()

    for hop in pending:
        outcome = _HOPS[hop](plan)
        write_layout_version(plan.state_root, hop)

    return outcome


def apply_plan(plan: MigrationPlan) -> MigrationOutcome:
    """Carry out every action in `plan`.

    Rewrites are not carried out here. They change a configuration value, and
    layout migration runs before configuration is loaded, so there is nothing
    to change yet -- they are for the caller to apply once there is.
    """
    diverted: list[Diversion] = []

    for action in plan.actions:
        if action.kind not in (ActionKind.MOVE, ActionKind.COPY):
            continue
        destination = action.destination
        if destination.exists():
            destination = _conflict_path(action.destination, plan.state_root)
            diverted.append(Diversion(planned=action.destination, actual=destination))
        if action.kind is ActionKind.MOVE:
            _move(action.source, destination)
        else:
            _copy(action.source, destination)

    return MigrationOutcome(diverted=tuple(diverted))


def _conflict_path(destination: Path, state_root: Path) -> Path:
    """Where something goes when its planned destination is occupied.

    Under one directory at the root of the data directory, keeping the shape it
    would have had, so that what collided with what stays legible. Never merged
    into the occupant: merging silently replaces same-named files, and import is
    offered from Settings at any time, so the occupant may be work the user did
    after choosing to start fresh.
    """
    try:
        relative = destination.relative_to(state_root)
    except ValueError:
        relative = Path(destination.name)
    return state_root / CONFLICTS_DIR_NAME / relative


def _copy(source: Path, destination: Path) -> None:
    """Duplicate `source` at `destination`, then check it arrived whole.

    Verified rather than trusted because nothing is deleted here, which makes a
    short copy recoverable -- the original is still where it was. What makes it
    dangerous is being reported as having worked, because the user then deletes
    the installation it came from.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        _copy_tree(source, destination)
    else:
        _copy_file(source, destination)
    _verify(source, destination)


def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, dirs_exist_ok=True)


def _copy_file(source: Path, destination: Path) -> None:
    shutil.copy2(source, destination)


def _verify(source: Path, destination: Path) -> None:
    """Compare what was asked for against what is now there.

    Bytes and file count, which is enough to catch a copy that stopped part way
    without re-reading everything that was just written.
    """
    expected = _measure(source)
    actual = _measure(destination)
    if expected != actual:
        raise MigrationError(
            f"copying {source} to {destination} did not arrive whole: "
            f"expected {expected[0]} bytes in {expected[1]} files, "
            f"found {actual[0]} in {actual[1]}"
        )


def _measure(path: Path) -> tuple[int, int]:
    if path.is_file():
        return path.stat().st_size, 1
    total = 0
    count = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
            count += 1
    return total, count


def _move(source: Path, destination: Path) -> None:
    """Rename `source` to `destination`, creating the parent it needs.

    `os.replace` rather than `shutil.move`, which falls back to copying and then
    removing its source. Both ends are inside the data directory, so this is a
    rename on one volume: atomic, and free regardless of how much is being
    moved.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)


_HOPS: dict[int, Callable[[MigrationPlan], MigrationOutcome]] = {
    1: apply_plan,
}
"""Each hop keyed by the version it produces.

A dictionary rather than a straight call because this is the shape that carries
someone who skipped releases: they run each hop in turn. Never renumber an entry
and never key one off the application version -- a hop is defined by the layout
it accepts, so renumbering silently changes which trees it runs against. The
same discipline `migrations.py` documents for its own schema chain.
"""
