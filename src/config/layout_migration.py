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
import os
from pathlib import Path
import re

import tomllib

from src.backend.utils.file_utilities import file_bytes_to_str, get_dir_size
from src.backend.utils.frameforge_index_cache import FrameForgeIndexCache
from src.backend.utils.working_dir import (
    JOBS_DIR_NAME,
    PROCESSING_DIR_NAME,
    WORKSPACE_DIR_NAME,
    normalise_path,
)
from src.config.paths import AppPaths
from src.plugins.loader import LOCAL_MANIFEST

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


class CopyPolicy(Enum):
    """Which files a copy action carries across.

    Most of the legacy tree is user data and must arrive byte for byte. A local
    plugin is different: its directory is a repository, and can contain a
    virtual environment, version-control data and generated caches alongside
    the files the plugin actually needs. The policy lives on the planned action
    so its displayed size, execution and verification cannot disagree.
    """

    ALL = "all"
    PLUGIN = "plugin"


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

    copy_policy: CopyPolicy = CopyPolicy.ALL
    """The source entries included by a copy; irrelevant to other actions."""


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


_LEGACY_STATE_LOCATIONS: tuple[tuple[str, ...], ...] = (
    ("bundle", "runtime"),
    ("runtime",),
)
"""Where a pre-migration installation keeps its state, relative to its root.

A release nests it inside the bundle directory PyInstaller writes; a source
checkout has it beside the code. The plugin directory is at the root either way.
"""


LEGACY_SEARCH_DEPTH = 2
"""How far below a chosen folder to look for an installation.

Two levels, because people pick the folder they extracted into rather than the
one they extracted, and sometimes the folder above that. Not more, because a
home directory is a plausible choice and walking a whole drive to find a
configuration file is a filesystem scan nobody asked for.
"""


def recognise_legacy_install(
    candidate: Path, max_depth: int = LEGACY_SEARCH_DEPTH
) -> LegacyInstall | None:
    """`candidate`, or something just below it, as a previous installation.

    Identified by holding configuration, rather than by its name or by an
    executable: the user named the folder, and an unpacked release nobody has
    run has nothing worth importing. Refusing is the useful answer there --
    accepting it would produce a migration that reports success having moved
    nothing.

    Searched breadth-first, so the shallowest match wins and a nested copy
    cannot shadow the installation it sits inside.
    """
    generation = [candidate]
    for _ in range(max_depth + 1):
        for root in generation:
            found = _install_at(root)
            if found is not None:
                return found
        generation = [
            child for root in generation for child in _children(root) if child.is_dir()
        ]
    return None


def _install_at(candidate: Path) -> LegacyInstall | None:
    for parts in _LEGACY_STATE_LOCATIONS:
        state = candidate.joinpath(*parts)
        if not _holds_configuration(state):
            continue
        return LegacyInstall(
            root=candidate, state=state, plugins=candidate / PLUGINS_DIR_NAME
        )
    return None


def _holds_configuration(state: Path) -> bool:
    config = state / "config"
    return (config / "user").is_dir() or (config / "program" / "conf.toml").is_file()


def missing_active_profile(paths: AppPaths) -> str:
    """The profile the program configuration names, if it is not there.

    A program configuration names the profile that was in use. If that profile is
    not among the ones present, NfoForge generates a fresh one under the same name
    and starts with default settings -- plugins off, trackers unconfigured. The
    migration reports complete success throughout, so the user sees settings that
    look wrong with nothing anywhere explaining why.

    Reachable whenever the installation being imported from names a profile it
    does not hold -- one deleted or renamed without the program configuration
    following, which nothing keeps in step.

    Not, as this once claimed, by importing into a directory that already holds
    profiles. The program configuration collides and is set aside alongside them,
    so the occupant keeps a consistent pair of its own and there is nothing to
    report.

    An unreadable program configuration reports nothing. That is already its own
    error with its own recovery, and a second vaguer complaint here would send the
    user looking for a missing profile when the problem is the file naming it.
    """
    if not paths.program.is_file():
        return ""
    try:
        document = tomllib.loads(paths.program.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return ""

    active = document.get("current_config")
    if not isinstance(active, str) or not active.strip():
        return ""
    active = active.strip()
    if (paths.user_configs / f"{active}.toml").is_file():
        return ""
    return active


@dataclass(frozen=True, slots=True)
class LegacySettings:
    """Path-valued settings read from a previous installation's profiles."""

    working_dirs: tuple[tuple[str, Path], ...]
    """Each labelled with the profiles naming it, deduplicated by path.

    Labelled because a user told which setting is wrong but not which profile
    holds it has been given the harder half of the problem. Deduplicated because
    profiles commonly share a working directory and the plan needs the set of
    directories, not one entry per profile.
    """

    configured_paths: tuple[tuple[str, str, Path], ...]
    """Each as the profile holding it, the setting's name, and the path.

    Kept apart rather than pre-joined into a label because the two consumers
    need different halves. A finding is about one profile's setting and needs
    both; a rewrite is about a value and applies to every profile, so a profile
    name on one is wrong however it reads.
    """


def read_legacy_settings(legacy: LegacyInstall) -> LegacySettings:
    """The settings a plan needs, read before any configuration has been loaded.

    The rewrites a migration plans come from settings, and settings live in the
    installation being migrated from. Reading them through the configuration
    layer is not available yet: that layer reads from the data directory, which
    is the thing the migration is still assembling.

    Boolean flags share the dependencies section with paths, so only path-valued
    settings are returned. A flag handed on as a path would be reported to the
    user as a setting pointing somewhere impossible.

    One damaged document does not cost the user every other profile's plan.
    """
    working_dirs: dict[Path, tuple[Path, list[str]]] = {}
    configured: list[tuple[str, str, Path]] = []

    for document_path in sorted((legacy.state / "config" / "user").glob("*.toml")):
        try:
            document = tomllib.loads(document_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
            continue
        profile = document_path.stem

        working_dir = document.get("general", {}).get("working_dir")
        if isinstance(working_dir, str) and working_dir.strip():
            # Keyed on the normalised path so that two profiles naming the same
            # directory with different casing or separators are recognised as
            # sharing it, rather than reported as two directories that happen to
            # look alike. The value keeps the path as the document wrote it: it
            # is what the user is shown, and resolving anchors anything not
            # already absolute to wherever the process started. Comparison
            # normalises both sides anyway, so matching does not depend on this.
            candidate = Path(working_dir)
            _, profiles = working_dirs.setdefault(
                normalise_path(candidate), (candidate, [])
            )
            profiles.append(profile)

        for name, value in document.get("dependencies", {}).items():
            if isinstance(value, bool) or not isinstance(value, str):
                continue
            if not value.strip():
                continue
            configured.append((profile, f"dependency {name}", Path(value)))

    return LegacySettings(
        working_dirs=tuple(
            (f"{', '.join(profiles)}: working directory", working_dir)
            for working_dir, profiles in working_dirs.values()
        ),
        configured_paths=tuple(configured),
    )


class FindingKind(Enum):
    """Something the user is told about rather than something that is done."""

    UNRECOGNISED_ENTRY = "unrecognised-entry"
    """Sits at the root of the data directory and is not part of any layout."""

    PATH_INSIDE_LEGACY_INSTALL = "path-inside-legacy-install"
    """A setting points into the old installation, which the user may delete."""

    RUN_FOLDER_IN_WORKING_DIR = "run-folder-in-working-dir"
    """Reclaimable run output in a directory the user chose. Never swept."""

    MISSING_CONFIGURED_PATH = "missing-configured-path"
    """A setting names something that is not on disk, wherever it points.

    The one case the other two cannot see. Both of those ask where a path sits
    relative to the installation being imported from, so a setting naming a
    different installation -- renamed, moved, or never picked -- is inside
    neither and would otherwise be repointed by nothing and reported by nothing.
    """


@dataclass(frozen=True, slots=True)
class Finding:
    kind: FindingKind
    path: Path
    size: int = 0
    detail: str = ""


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    actions: tuple[PlannedAction, ...]
    state_root: Path = Path()
    """The data directory this plan is for.

    Carried on the plan rather than passed alongside it, so that applying one
    needs nothing but the plan the user read. Anything derived at apply time
    from a second argument could differ from what they agreed to.
    """

    legacy_root: Path | None = None
    """The installation this plan imports from, if it imports from one.

    Kept so the record written afterwards can say where the data came from,
    which is the first thing anyone asks when something is missing.
    """

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
    configured_paths: Iterable[tuple[str, str, Path]] = (),
    working_dirs: Iterable[tuple[str, Path]] = (),
    shipped_plugins: Path | None = None,
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
                / WORKSPACE_DIR_NAME
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
                    destination=state_root
                    / WORKSPACE_DIR_NAME
                    / PROCESSING_DIR_NAME
                    / entry.name,
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

    workspace = state_root / WORKSPACE_DIR_NAME
    for label, working_dir in working_dirs:
        if normalise_path(working_dir) == normalise_path(state_root):
            repoint = PlannedAction(
                kind=ActionKind.REWRITE,
                source=working_dir,
                destination=workspace,
                size=0,
                detail="working directory",
            )
            if repoint not in actions:
                actions.append(repoint)
            continue
        if legacy is not None and _is_inside(working_dir, legacy.root):
            # Nothing imports a working directory -- it is not part of the layout
            # being copied -- so the setting survives still naming a folder the
            # summary goes on to invite the user to delete, with their saved jobs
            # in it. Reported instead of its run folders: one finding about the
            # folder beats two, and "you can reclaim space here" reads oddly
            # against "this is about to stop existing".
            findings.append(
                Finding(
                    kind=FindingKind.PATH_INSIDE_LEGACY_INSTALL,
                    path=working_dir,
                    detail=label,
                )
            )
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
        shipped_ids = _plugin_ids(shipped_plugins) if shipped_plugins else frozenset()
        for entry in _children(legacy.plugins):
            if not entry.is_dir() or _plugin_id(entry) in shipped_ids:
                continue
            actions.append(
                _copy(
                    entry,
                    state_root / PLUGINS_DIR_NAME / entry.name,
                    copy_policy=CopyPolicy.PLUGIN,
                )
            )

        legacy_tools = legacy.state / LEGACY_TOOLS_DIR_NAME
        for profile, setting, configured in configured_paths:
            if _is_inside(configured, legacy_tools):
                remainder = normalise_path(configured).relative_to(
                    normalise_path(legacy_tools)
                )
                # Named for the setting and not the profile it was read from.
                # Applying a rewrite walks every profile and repoints any holding
                # that value, so the action belongs to all of them: two profiles
                # sharing a tool are one operation, and the profile actually
                # written is named by the report at the point it is written.
                repoint = PlannedAction(
                    kind=ActionKind.REWRITE,
                    source=configured,
                    destination=state_root / TOOLS_DIR_NAME / remainder,
                    size=0,
                    detail=setting,
                )
                if repoint not in actions:
                    actions.append(repoint)
            elif not configured.exists():
                # Checked before the legacy-install case, because "emptying that
                # folder will break this" is the wrong thing to say about a
                # setting that is already broken. Nothing here is guessed at: a
                # replacement would be this code inventing one.
                findings.append(
                    Finding(
                        kind=FindingKind.MISSING_CONFIGURED_PATH,
                        path=configured,
                        detail=f"{profile}: {setting}",
                    )
                )
            elif _is_inside(configured, legacy.root):
                # A finding is the opposite case: it is about one profile's
                # setting, which nothing is going to change, so the profile is
                # the only way the user knows where to go.
                findings.append(
                    Finding(
                        kind=FindingKind.PATH_INSIDE_LEGACY_INSTALL,
                        path=configured,
                        detail=f"{profile}: {setting}",
                    )
                )

    return MigrationPlan(
        actions=tuple(actions),
        state_root=state_root,
        legacy_root=legacy.root if legacy is not None else None,
        findings=tuple(findings),
    )


def _copy(
    source: Path,
    destination: Path,
    copy_policy: CopyPolicy = CopyPolicy.ALL,
) -> PlannedAction:
    return PlannedAction(
        kind=ActionKind.COPY,
        source=source,
        destination=destination,
        size=copy_measure(source, copy_policy)[0],
        copy_policy=copy_policy,
    )


_ACTION_HEADINGS = {
    ActionKind.MOVE: "Move within the data directory",
    ActionKind.COPY: "Copy from the previous installation",
    ActionKind.REWRITE: "Repoint these settings",
}

_FINDING_HEADINGS = {
    FindingKind.UNRECOGNISED_ENTRY: "Left in place, not part of the layout",
    FindingKind.RUN_FOLDER_IN_WORKING_DIR: "Run output you can delete",
    FindingKind.PATH_INSIDE_LEGACY_INSTALL: (
        "Settings pointing into the previous installation"
    ),
    FindingKind.MISSING_CONFIGURED_PATH: "Settings naming something that is not there",
}
"""A heading per kind, because the three ask different things.

A leftover entry asks to be looked at and run output asks whether the space is
wanted back, but a setting pointing into the old installation is a warning about
deleting that folder -- a consequence rather than an observation. Under one
heading it reads like the other two, which is exactly the line that must not be
skimmed.
"""


def render_plan(plan: MigrationPlan) -> str:
    """A plan as text, grouped by what happens and sized.

    Deliberately plain text rather than anything the GUI owns, so that the same
    output can be read in a dialog, written beside a migration as a record, or
    printed by a rehearsal that never starts the application at all.
    """
    sections: list[str] = []

    for kind, heading in _ACTION_HEADINGS.items():
        matching = [action for action in plan.actions if action.kind is kind]
        if not matching:
            continue
        sized = kind is not ActionKind.REWRITE
        total = sum(action.size for action in matching)
        lines = [f"{heading} ({file_bytes_to_str(total)}):" if sized else f"{heading}:"]
        for action in matching:
            prefix = f"{action.detail}: " if action.detail else ""
            suffix = f" ({file_bytes_to_str(action.size)})" if sized else ""
            lines.append(f"  {prefix}{action.source} -> {action.destination}{suffix}")
        sections.append("\n".join(lines))

    for kind, heading in _FINDING_HEADINGS.items():
        matching = [finding for finding in plan.findings if finding.kind is kind]
        if not matching:
            continue
        total = sum(finding.size for finding in matching)
        lines = [f"{heading} ({file_bytes_to_str(total)}):" if total else f"{heading}:"]
        for finding in matching:
            suffix = f" ({file_bytes_to_str(finding.size)})" if finding.size else ""
            detail = f" -- {finding.detail}" if finding.detail else ""
            lines.append(f"  {finding.path}{suffix}{detail}")
        sections.append("\n".join(lines))

    if not sections:
        return "Nothing to migrate."
    return "\n\n".join(sections)


def _plugin_ids(directory: Path) -> frozenset[str]:
    """Every plugin ID declared directly below `directory`."""
    found = {_plugin_id(entry) for entry in _children(directory) if entry.is_dir()}
    return frozenset(plugin_id for plugin_id in found if plugin_id is not None)


def _plugin_id(directory: Path) -> str | None:
    """The ID a plugin declares, or None if there is no readable manifest.

    None for a directory that is not a plugin, which is deliberately not the
    same as an ID that matches nothing: a directory with no manifest is still
    the user's and is still imported.
    """
    manifest = directory / LOCAL_MANIFEST
    try:
        declared = tomllib.loads(manifest.read_text(encoding="utf-8")).get("id")
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None
    return declared.strip() if isinstance(declared, str) and declared.strip() else None


_PLUGIN_IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".cache",
        ".git",
        ".hg",
        ".hypothesis",
        ".mypy_cache",
        ".nox",
        ".pyright",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "__pypackages__",
        "node_modules",
        "venv",
    }
)
"""Disposable directories excluded wherever they occur in a plugin tree."""

_PLUGIN_IGNORED_ROOT_DIRECTORY_NAMES = frozenset({"build", "dist", "htmlcov"})
"""Generated output excluded only at a plugin repository's root.

Nested packages are allowed to use ordinary words such as ``build`` as module
or resource names. Restricting these three to the repository root avoids
silently removing such a package while still catching the conventional output
directories produced by Python build and coverage tools.
"""

_PLUGIN_IGNORED_FILE_NAMES = frozenset(
    {".coverage", ".ds_store", "desktop.ini", "thumbs.db"}
)
_PLUGIN_IGNORED_FILE_SUFFIXES = (".pyc", ".pyo")


def copy_ignored_names(
    policy: CopyPolicy,
    source_root: Path,
    directory: Path,
    names: Iterable[str],
) -> set[str]:
    """Entries omitted from one directory under ``policy``.

    This is shared by planning and applying. Keeping one predicate is the
    important property: the size shown before migration, the files copied and
    the source side of verification must describe exactly the same tree.

    A virtual environment with an unconventional name is recognised by its
    ``pyvenv.cfg`` marker. Common ``.venv`` and ``venv`` directories are also
    excluded when incomplete, which is useful after an interrupted environment
    creation.
    """
    if policy is CopyPolicy.ALL:
        return set()

    ignored: set[str] = set()
    at_root = directory == source_root
    for name in names:
        entry = directory / name
        folded = name.casefold()
        if entry.is_dir():
            if (
                folded in _PLUGIN_IGNORED_DIRECTORY_NAMES
                or (at_root and folded in _PLUGIN_IGNORED_ROOT_DIRECTORY_NAMES)
                or (entry / "pyvenv.cfg").is_file()
            ):
                ignored.add(name)
            continue
        if (
            folded in _PLUGIN_IGNORED_FILE_NAMES
            or folded.startswith(".coverage.")
            or folded.endswith(_PLUGIN_IGNORED_FILE_SUFFIXES)
        ):
            ignored.add(name)
    return ignored


def copy_measure(path: Path, policy: CopyPolicy) -> tuple[int, int]:
    """Bytes and file count that a copy action will carry from ``path``."""
    if path.is_file():
        return path.stat().st_size, 1

    total = 0
    count = 0
    for current, directories, files in os.walk(path):
        directory = Path(current)
        ignored = copy_ignored_names(policy, path, directory, (*directories, *files))
        directories[:] = [name for name in directories if name not in ignored]
        for name in files:
            if name in ignored:
                continue
            entry = directory / name
            if entry.is_file():
                total += entry.stat().st_size
                count += 1
    return total, count


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
