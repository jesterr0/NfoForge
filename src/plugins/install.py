"""Putting a plugin into the data folder, having first checked it is one.

Dropping a folder into `plugins/` still works and is still the documented
route. This module is for the case where that route goes wrong quietly: the
archive was unpacked one level too deep, the manifest is missing a field, the
module it names is not there, or its id or module name is already claimed by a
plugin that is installed or shipped. Every one of those is otherwise discovered
on the *next* launch, in the discovered-plugins table, with the folder already
on disk and nothing offering to remove it.

So the checks here are the loader's own checks, run earlier. `read_local_manifest`
and `validate_plugin_id` are imported rather than reimplemented: an installer
that disagreed with the loader about what a plugin is would be worse than no
installer, because it would install things that do not load.

What this deliberately does not do is import the plugin. A plugin is trusted
Python code that runs inside NfoForge's process, and a validation step that
executed it would run that code from a file dialog, before the user has been
shown what they are about to install. Restarting is required for a new plugin
to load anyway, so there is nothing to gain by importing it early.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

from src.config.layout_migration import CopyPolicy, copy_ignored_names
from src.config.paths import AppPaths
from src.exceptions import PluginError
from src.logger.nfo_forge_logger import LOG
from src.plugins.loader import (
    LOCAL_MANIFEST,
    declared_plugins,
    read_local_manifest,
)
from src.plugins.manager import validate_plugin_id
from src.utils.safe_archive import UnsafeArchiveError, extract_safely, safe_members

MAX_PLUGIN_ENTRIES = 4096
MAX_PLUGIN_BYTES = 128 * 1024 * 1024
"""A plugin repository with its tests, docs and a compiled package.

Larger than a configuration bundle is allowed and smaller than a toolchain,
because a plugin is source code. A repository that reaches this has a virtual
environment or a build artifact in it that the copy filter would have dropped
anyway.
"""


ARCHIVE_DIR_NAME = "old_plugins"
"""Where a replaced plugin is kept, inside the plugins folder beside it."""


class PluginInstallError(Exception):
    """An install was refused, with a reason worth showing a user."""


@dataclass(frozen=True, slots=True)
class InstallOutcome:
    destination: Path
    replaced: Path | None
    """Where the previous copy was moved to, if this replaced one."""


@dataclass(frozen=True, slots=True)
class PluginCandidate:
    """A directory that has been proved to hold one installable plugin."""

    root: Path
    plugin_id: str
    module: str
    object_name: str
    directory_name: str
    """What it will be called under `plugins/`.

    Its own name wherever there is one, so an installed plugin looks on disk
    like the repository it came from and a user who later edits it in place
    recognises it.
    """


def inspect_folder(folder: Path) -> PluginCandidate:
    """Describe the plugin in `folder`, or say why there is not one.

    Accepts the folder itself, or a single directory inside it that holds the
    manifest. That second shape is what a downloaded and unpacked repository
    looks like -- `my-plugin-main/nfoforge-plugin.toml` -- and is the mistake
    that drop-in installation most often produces: the wrapper goes into
    `plugins/`, the loader finds no manifest directly below it, and the plugin
    is silently not a candidate.
    """
    if not folder.is_dir():
        raise PluginInstallError(f"'{folder}' is not a folder.")

    root = folder if (folder / LOCAL_MANIFEST).is_file() else _nested_root(folder)
    try:
        candidate = read_local_manifest(root, root / LOCAL_MANIFEST)
        validate_plugin_id(candidate.plugin_id)
    except PluginError as error:
        raise PluginInstallError(
            f"'{root.name}' is not a usable plugin: {error}"
        ) from error

    if not _module_present(root, candidate.module):
        raise PluginInstallError(
            f"'{root.name}' declares the module '{candidate.module}', which is "
            "not in the folder. A plugin's module must sit directly beside its "
            f"{LOCAL_MANIFEST}."
        )

    return PluginCandidate(
        root=root,
        plugin_id=candidate.plugin_id,
        module=candidate.module,
        object_name=candidate.object_name,
        directory_name=root.name,
    )


def _nested_root(folder: Path) -> Path:
    """The one directory below `folder` holding a manifest.

    One, not the first: a folder holding several plugins is a plugins
    directory, not a plugin, and guessing which was meant would install
    something the user did not choose.
    """
    try:
        candidates = [
            entry
            for entry in sorted(folder.iterdir())
            if entry.is_dir() and (entry / LOCAL_MANIFEST).is_file()
        ]
    except OSError as error:
        raise PluginInstallError(f"'{folder}' could not be read: {error}") from error

    if not candidates:
        raise PluginInstallError(
            f"No {LOCAL_MANIFEST} was found in '{folder.name}', or in any "
            "folder directly inside it. Choose the plugin's own folder -- the "
            f"one holding {LOCAL_MANIFEST}."
        )
    if len(candidates) > 1:
        names = ", ".join(entry.name for entry in candidates)
        raise PluginInstallError(
            f"'{folder.name}' holds more than one plugin ({names}). Choose one "
            "of them rather than the folder holding them."
        )
    return candidates[0]


def _module_present(root: Path, module: str) -> bool:
    """Whether the declared module is somewhere the loader would find it.

    The loader resolves the module against the plugin root alone, so a manifest
    naming a module that is not there installs cleanly and then fails to load.
    Checked by shape rather than by importing: a package directory, a compiled
    package, or a single module file.
    """
    package = root / module
    if (package / "__init__.py").is_file() or (package / "__init__.pyd").is_file():
        return True
    return any((root / f"{module}{suffix}").is_file() for suffix in (".py", ".pyd"))


@contextmanager
def extracted_archive(archive: Path) -> Iterator[PluginCandidate]:
    """Unpack `archive` somewhere temporary and describe the plugin in it.

    A context manager because the extracted tree has to outlive inspection --
    the user is shown what was found and then decides -- and has to be removed
    whether they accept or decline.
    """
    if not archive.is_file():
        raise PluginInstallError(f"'{archive}' is not a file.")

    with tempfile.TemporaryDirectory(prefix="nfoforge-plugin-") as workspace:
        destination = Path(workspace)
        try:
            with zipfile.ZipFile(archive) as opened:
                members = safe_members(opened, MAX_PLUGIN_ENTRIES, MAX_PLUGIN_BYTES)
                if not members:
                    raise PluginInstallError(f"'{archive.name}' is empty.")
                extract_safely(opened, destination, members, MAX_PLUGIN_BYTES)
        except UnsafeArchiveError as error:
            raise PluginInstallError(str(error)) from error
        except zipfile.BadZipFile as error:
            raise PluginInstallError(
                f"'{archive.name}' is not a readable zip: {error}"
            ) from error
        except OSError as error:
            raise PluginInstallError(
                f"'{archive.name}' could not be unpacked: {error}"
            ) from error

        candidate = inspect_folder(destination)
        if candidate.root == destination:
            # The manifest sat at the archive root, so there is no repository
            # name to keep. The ID is the plugin's permanent identity and is
            # already constrained to characters a directory may use.
            candidate = PluginCandidate(
                root=candidate.root,
                plugin_id=candidate.plugin_id,
                module=candidate.module,
                object_name=candidate.object_name,
                directory_name=candidate.plugin_id,
            )
        yield candidate


def resolve_conflict(candidate: PluginCandidate, paths: AppPaths) -> Path | None:
    """The installed directory this would replace, or None for a fresh install.

    Not every clash is a problem. A matching id in the user's own plugins
    folder is the ordinary case of updating a plugin, and refusing it -- which
    this did at first -- leaves deleting the folder by hand as the only route,
    which is the work the installer exists to remove. So that one is reported
    back as something to replace rather than raised.

    The two that remain are genuinely unresolvable and are raised:

    - An id a *shipped example* declares. A release's example cannot be
      replaced; the user's copy would register first and the example would be
      reported as broken on every launch.
    - A module name some *other* plugin declares. The loader resolves a module
      by name and refuses a second one "already loaded from a different
      location", so the two cannot coexist whichever is installed second.
      Plugins built from the same example routinely share one, which makes this
      the likelier clash -- and left to startup it reads as an install that
      silently did nothing.
    """
    for found in declared_plugins(paths.plugin_examples):
        if found.plugin_id == candidate.plugin_id:
            raise PluginInstallError(
                f"A plugin with the id '{candidate.plugin_id}' ships with "
                "NfoForge. Two plugins cannot share an id; only one of them "
                "would load."
            )
        if found.module and found.module == candidate.module:
            raise PluginInstallError(
                f"A plugin using the module '{candidate.module}' ships with "
                "NfoForge. Two plugins cannot share a module name; only one "
                "of them would load."
            )

    replaces: Path | None = None
    for found in declared_plugins(paths.plugins):
        if found.plugin_id == candidate.plugin_id:
            replaces = found.root
            continue
        if found.module and found.module == candidate.module:
            raise PluginInstallError(
                f"The plugin already installed at '{found.root.name}' uses the "
                f"module '{candidate.module}'. Two plugins cannot share a "
                "module name; only one of them would load."
            )

    loaded = sys.modules.get(candidate.module)
    if loaded is not None:
        module_file = getattr(loaded, "__file__", None)
        allowed_roots = tuple(
            root for root in (candidate.root, replaces) if root is not None
        )
        if module_file is None or not any(
            _is_below(Path(module_file), root) for root in allowed_roots
        ):
            raise PluginInstallError(
                f"The module '{candidate.module}' is already loaded from a "
                "different location. This plugin would install successfully "
                "but fail to load after restart."
            )
    return replaces


def install(candidate: PluginCandidate, paths: AppPaths) -> InstallOutcome:
    """Copy `candidate` into the user's plugins directory.

    Filtered through the migration's own copy predicate, so a repository
    carrying a virtual environment, a `.git` directory, build output or
    bytecode arrives as source rather than as a copy of somebody's working
    tree. Nothing else about the tree is changed: tests, documentation and
    resources come across.

    A plugin already installed under this id is moved aside rather than
    written over, so an update that turns out to be worse than what it replaced
    is something the user can undo by hand.
    """
    replaces = resolve_conflict(candidate, paths)

    replaced: Path | None = None
    try:
        paths.plugins.mkdir(parents=True, exist_ok=True)
        # Copy and re-inspect before moving an installed version.  Besides
        # making ordinary copy failures harmless, this supports selecting the
        # installed folder itself: its contents are safely staged before that
        # folder is archived.
        with tempfile.TemporaryDirectory(
            prefix=".nfoforge-install-", dir=paths.plugins
        ) as workspace:
            staged = Path(workspace) / candidate.directory_name
            shutil.copytree(
                candidate.root,
                staged,
                ignore=lambda directory, names: copy_ignored_names(
                    CopyPolicy.PLUGIN, candidate.root, Path(directory), names
                ),
            )
            staged_candidate = inspect_folder(staged)
            if (
                staged_candidate.plugin_id != candidate.plugin_id
                or staged_candidate.module != candidate.module
                or staged_candidate.object_name != candidate.object_name
            ):
                raise PluginInstallError(
                    "The staged plugin no longer matches the manifest that was "
                    "approved. Nothing was installed."
                )

            try:
                replaced = _archive(replaces) if replaces is not None else None
                destination = _free_destination(paths.plugins, candidate.directory_name)
                staged.replace(destination)
            except OSError:
                if replaced is not None and replaces is not None:
                    try:
                        shutil.move(str(replaced), str(replaces))
                    except OSError as rollback_error:
                        raise PluginInstallError(
                            f"'{candidate.plugin_id}' could not be installed, and "
                            "the previous copy could not be restored automatically: "
                            f"{rollback_error}. It is still available at {replaced}."
                        ) from rollback_error
                raise
    except PluginInstallError:
        raise
    except OSError as error:
        raise PluginInstallError(
            f"'{candidate.plugin_id}' could not be installed: {error}"
        ) from error

    LOG.info(
        LOG.LOG_SOURCE.FE,
        f"{'Updated' if replaced else 'Installed'} plugin "
        f"'{candidate.plugin_id}' at {destination}",
    )
    return InstallOutcome(destination=destination, replaced=replaced)


def _is_below(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _archive(existing: Path) -> Path:
    """Move an installed plugin aside, keeping it findable.

    Under `old_plugins` beside it, timestamped, which is the shape
    `ConfigManager._backup_path` already uses for a replaced profile. Moved
    rather than deleted because nothing in this application's config layer
    deletes the user's own files, and a plugin repository can hold work the
    user did in place.

    Safe to keep inside `plugins/` because the loader looks exactly one level
    down for a manifest: `old_plugins` has none of its own, and what is below
    it is a level too deep to be seen.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = existing.parent / ARCHIVE_DIR_NAME
    archive_dir.mkdir(parents=True, exist_ok=True)
    destination = archive_dir / f"{existing.name}_{stamp}"
    counter = 1
    while destination.exists():
        destination = archive_dir / f"{existing.name}_{stamp}_{counter}"
        counter += 1
    return Path(shutil.move(str(existing), str(destination)))


def _free_destination(plugins: Path, name: str) -> Path:
    """A directory name nothing is using yet.

    The ID is what must be unique and has already been checked, so a name
    already in use belongs to a different plugin that happens to have been
    distributed under the same folder name. Suffixed rather than refused: the
    folder name is incidental, and refusing over it would block an install for
    a reason the user cannot act on.
    """
    destination = plugins / name
    counter = 2
    while destination.exists():
        destination = plugins / f"{name} ({counter})"
        counter += 1
    return destination
