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
from datetime import datetime
import os
from pathlib import Path
import shutil
from typing import Any

import tomlkit

from src.backend.utils.file_utilities import file_bytes_to_str
from src.backend.utils.working_dir import CURRENT_DIR, normalise_path
from src.config.layout_migration import (
    ActionKind,
    LegacyInstall,
    LegacySettings,
    MigrationPlan,
    PlannedAction,
    missing_active_profile,
    plan_migration,
    read_legacy_settings,
    recognise_legacy_install,
)
from src.config.layout_version import (
    CURRENT_LAYOUT_VERSION,
    pending_hops,
    read_layout_version,
    record_import,
    write_layout_version,
)
from src.config.paths import AppPaths
from src.logger.nfo_forge_logger import LOG

Progress = Callable[[str], None]
"""Reports the step about to run, for a splash screen or a log.

A message per action rather than a fraction. Relocation inside the data directory
is renames and finishes immediately, so the wait is entirely the copy from the
previous installation -- naming what is being copied and how large it is turns an
unexplained pause into a step with an end.
"""

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
class MigrationRun:
    """A migration that happened: what was planned, and what came of it.

    Both, because the summary shown afterwards needs the plan to say what moved
    and the outcome to say what could not. Returning only one would have the
    caller rebuild the other and risk describing something that did not happen.
    """

    plan: MigrationPlan
    outcome: MigrationOutcome
    missing_profile: str = ""
    """The profile the program configuration names, if it did not arrive.

    Checked after the copies rather than planned, because it is a property of
    what ended up in the folder: an import whose profiles diverted leaves a
    program configuration naming one that is sitting somewhere else.
    """


@dataclass(frozen=True, slots=True)
class MigrationOutcome:
    diverted: tuple[Diversion, ...] = ()
    rewritten: tuple[str, ...] = ()
    """Which settings were repointed, named by profile, for the summary."""


def startup_migration(
    paths: AppPaths,
    decide: Callable[[LegacyInstall | None], LegacyInstall | None],
    probe_root: Path | None = None,
    progress: Progress | None = None,
) -> MigrationRun | None:
    """Bring the data directory up to date, asking `decide` what to import.

    Runs before configuration is loaded, because configuration is read from the
    directory this is still assembling. Returns None when there was nothing to
    do, which is the path almost every launch takes: no discovery, no question,
    no plan.

    `decide` is handed whatever was found beside the executable and answers with
    the installation to import from -- the one offered, a different one the user
    picked, or None to start fresh. Declining is a choice about the old
    installation and not about this one, so saved jobs and run output already in
    the data directory are relocated either way. They accumulated there under the
    old layout regardless of where the application was installed, and leaving
    them would hide a user's saved jobs behind a decision about something else.
    """
    if not pending_hops(read_layout_version(paths.state_root)):
        return None

    found = recognise_legacy_install(probe_root or CURRENT_DIR)
    chosen = decide(found)
    plan = _plan_for(paths, chosen)
    outcome = migrate_layout(plan, progress=progress)

    if found is not None and chosen is None:
        # Recorded apart from "nothing was found", because the two are different
        # facts. One day a user asks why they were never offered the import, and
        # the answer has to be in the record.
        write_layout_version(
            paths.state_root, CURRENT_LAYOUT_VERSION, record={"import_declined": True}
        )
    return MigrationRun(
        plan=plan, outcome=outcome, missing_profile=missing_active_profile(paths)
    )


def import_legacy(
    paths: AppPaths, legacy: LegacyInstall, progress: Progress | None = None
) -> MigrationRun:
    """Import a previous installation into a data directory already in use.

    Offered from Settings at any time, which is why it cannot go through
    `startup_migration`: that refuses an already-current tree, correctly for a
    hop and wrongly for an import, so routed through it the Settings action would
    silently do nothing. Nor through `migrate_layout`, for the same reason.

    The layout version is left alone. An import is not a hop -- a hop happens
    once per tree and is what the version tracks, while this can happen any number
    of times -- so advancing it would claim work that did not happen.

    Anything whose destination is occupied is diverted rather than merged, so
    whatever the user produced before importing stays exactly where it is.
    """
    plan = _plan_for(paths, legacy)
    outcome = apply_plan(plan, progress=progress)
    record_import(paths.state_root, _record(plan, outcome))
    return MigrationRun(
        plan=plan, outcome=outcome, missing_profile=missing_active_profile(paths)
    )


def _plan_for(paths: AppPaths, legacy: LegacyInstall | None) -> MigrationPlan:
    """What to do, given the installation the user settled on."""
    settings = (
        read_legacy_settings(legacy)
        if legacy is not None
        else LegacySettings(working_dirs=(), configured_paths=())
    )
    return plan_migration(
        paths.state_root,
        legacy=legacy,
        configured_paths=settings.configured_paths,
        working_dirs=settings.working_dirs,
        shipped_plugins=paths.plugin_examples,
    )


def migrate_layout(
    plan: MigrationPlan, progress: Progress | None = None
) -> MigrationOutcome:
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
        outcome = _HOPS[hop](plan, progress)
        write_layout_version(plan.state_root, hop, record=_record(plan, outcome))

    return outcome


def _record(plan: MigrationPlan, outcome: MigrationOutcome) -> dict[str, object]:
    """What happened, in the form someone reads afterwards.

    Where the data came from, when, and every entry that moved, was copied, or
    collided. Without it the only account of a migration is a dialog nobody
    kept, and "where did my templates go" has no answer.
    """
    return {
        "migrated_at": datetime.now().isoformat(timespec="seconds"),
        "legacy_source": str(plan.legacy_root) if plan.legacy_root else None,
        "moved": _entries(plan, ActionKind.MOVE),
        "copied": _entries(plan, ActionKind.COPY),
        "diverted": [
            {"planned": str(one.planned), "actual": str(one.actual)}
            for one in outcome.diverted
        ],
        "rewritten": list(outcome.rewritten),
    }


def _entries(plan: MigrationPlan, kind: ActionKind) -> list[dict[str, str]]:
    return [
        {"source": str(action.source), "destination": str(action.destination)}
        for action in plan.actions
        if action.kind is kind
    ]


def apply_plan(
    plan: MigrationPlan, progress: Progress | None = None
) -> MigrationOutcome:
    """Carry out every action in `plan`.

    Rewrites run last, because they edit the profile documents the copies put
    there. Editing the migrated copy rather than the installation it came from
    means the original keeps its original values, so a user reviewing that
    folder later still sees what it said.
    """
    diverted: list[Diversion] = []

    for action in plan.actions:
        if action.kind not in (ActionKind.MOVE, ActionKind.COPY):
            continue
        if progress is not None:
            progress(_describe(action))
        destination = action.destination
        if destination.exists():
            destination = _conflict_path(action.destination, plan.state_root)
            diverted.append(Diversion(planned=action.destination, actual=destination))
        if action.kind is ActionKind.MOVE:
            _move(action.source, destination)
        else:
            _copy(action.source, destination)

    rewrites = tuple(
        action for action in plan.actions if action.kind is ActionKind.REWRITE
    )
    return MigrationOutcome(
        diverted=tuple(diverted),
        rewritten=_apply_rewrites(rewrites, plan.state_root),
    )


def _apply_rewrites(
    rewrites: tuple[PlannedAction, ...], state_root: Path
) -> tuple[str, ...]:
    """Repoint every setting a rewrite names, in each migrated profile.

    Matched by comparing paths rather than strings, so a setting written with a
    different separator or casing is still recognised as the same place.

    Rewritten with `tomlkit` so the document keeps its comments, ordering and
    spacing. This is the user's file and a migration has no business reformatting
    it; only the values it names may change.
    """
    if not rewrites:
        return ()

    applied: list[str] = []
    for document_path in sorted((state_root / "config" / "profiles").glob("*.toml")):
        try:
            document = tomlkit.parse(document_path.read_text(encoding="utf-8"))
        except Exception as error:
            # Unreadable or malformed: skipped rather than fatal, so one damaged
            # profile does not cost the user the repointing of all the others.
            # Broad because tomlkit raises several unrelated types for a bad
            # document, and none of them matter here beyond "cannot be read".
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Could not repoint settings in {document_path}, so its paths "
                f"still name their old locations: {error}",
            )
            continue
        changed = _repoint(document, rewrites)
        if not changed:
            continue
        try:
            document_path.write_text(tomlkit.dumps(document), encoding="utf-8")
        except OSError as error:
            raise MigrationError(
                f"{document_path} could not be updated: {error}"
            ) from error
        applied.extend(f"{document_path.stem}: {detail}" for detail in changed)
    return tuple(applied)


def _repoint(document: Any, rewrites: tuple[PlannedAction, ...]) -> list[str]:
    """Replace any value in `document` that a rewrite names, in place."""
    changed: list[str] = []
    for table_name, keys in (
        ("general", ("working_dir",)),
        ("dependencies", None),
    ):
        table = document.get(table_name)
        if not isinstance(table, dict):
            continue
        for key in keys if keys is not None else tuple(table.keys()):
            value = table.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            for rewrite in rewrites:
                if normalise_path(Path(value)) != normalise_path(rewrite.source):
                    continue
                table[key] = str(rewrite.destination)
                changed.append(rewrite.detail or key)
                break
    return changed


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


_HOPS: dict[int, Callable[[MigrationPlan, Progress | None], MigrationOutcome]] = {
    1: apply_plan,
}
"""Each hop keyed by the version it produces.

A dictionary rather than a straight call because this is the shape that carries
someone who skipped releases: they run each hop in turn. Never renumber an entry
and never key one off the application version -- a hop is defined by the layout
it accepts, so renumbering silently changes which trees it runs against. The
same discipline `migrations.py` documents for its own schema chain.
"""


def _describe(action: PlannedAction) -> str:
    """What to say about a step while it runs, in the user's terms.

    Named by destination rather than source: the user is watching their data
    arrive somewhere, and for the renames the source no longer exists by the time
    they could look. Size only where it explains a wait -- a rename does not.
    """
    what = action.destination.name
    if action.kind is ActionKind.MOVE:
        return f"Moving {what}"
    if action.kind is ActionKind.COPY:
        return f"Copying {what} ({file_bytes_to_str(action.size)})"
    return f"Updating {action.detail or what}"
