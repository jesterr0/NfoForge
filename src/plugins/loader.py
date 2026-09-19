from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib import machinery, metadata, util
from pathlib import Path
import sys
import tomllib
import traceback
from typing import Any

import tomlkit

from src.config.paths import DEV_PLUGINS_ENV_VAR, default_paths, dev_plugin_dirs
from src.exceptions import PluginError
from src.logger.nfo_forge_logger import LOG
from src.plugins.api import PluginDefinition, PluginRecord
from src.plugins.manager import PluginManager

LOCAL_MANIFEST = "nfoforge-plugin.toml"
ENTRY_POINT_GROUP = "nfoforge.plugins"


@dataclass(frozen=True, slots=True)
class PluginLoadFailure:
    source: str
    reason: str

    def __str__(self) -> str:
        return f"{self.source}: {self.reason}"


@dataclass(frozen=True, slots=True)
class PluginLoadReport:
    loaded: tuple[PluginRecord, ...]
    failures: tuple[PluginLoadFailure, ...]


@dataclass(frozen=True, slots=True)
class LocalCandidate:
    plugin_id: str
    root: Path
    module: str
    object_name: str


def declared_identity(directory: Path) -> tuple[str, str] | None:
    """The id and module a directory claims, or None if it claims nothing.

    Deliberately weaker than `read_local_manifest`, which raises. This answers
    "what does this say it is", which is the question a collision check asks --
    and it has to be answerable about a neighbour whose own manifest is broken,
    because a broken plugin still occupies its id and its module name as far as
    the next launch is concerned.

    The module comes back as an empty string when none is declared, so that a
    manifest missing it cannot collide with every other manifest missing it.
    """
    try:
        document = tomllib.loads(
            (directory / LOCAL_MANIFEST).read_text(encoding="utf-8")
        )
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None

    declared_id = document.get("id")
    if not isinstance(declared_id, str) or not declared_id.strip():
        return None
    declared_module = document.get("module")
    module = declared_module.strip() if isinstance(declared_module, str) else ""
    return declared_id.strip(), module


@dataclass(frozen=True, slots=True)
class InstalledPlugin:
    """What a directory below a plugins folder claims to be.

    Claims, not facts: assembled from `declared_identity`, so a plugin whose
    manifest is otherwise broken still appears here. That is the point -- a
    broken plugin still occupies its id and its module name as far as the next
    launch is concerned, so anything asking "is this taken" has to see it.
    """

    root: Path
    plugin_id: str
    module: str


def declared_plugins(directory: Path) -> tuple[InstalledPlugin, ...]:
    """Every plugin declaring an id directly below `directory`.

    Not deduplicated by id. Two directories declaring the same id is a state
    the filesystem allows and the loader reports as a duplicate, and collapsing
    them here would hide the second one's module from a collision check.

    An unreadable directory yields nothing rather than raising: callers ask
    this about folders that may not exist yet.
    """
    try:
        entries = sorted(entry for entry in directory.iterdir() if entry.is_dir())
    except OSError:
        return ()

    found: list[InstalledPlugin] = []
    for entry in entries:
        declared = declared_identity(entry)
        if declared is not None:
            found.append(InstalledPlugin(entry, declared[0], declared[1]))
    return tuple(found)


def read_local_manifest(root: Path, manifest: Path) -> LocalCandidate:
    """Validate one `nfoforge-plugin.toml` and describe what it declares.

    Module level rather than a method because installing a plugin has to answer
    the same question before anything is copied, and the answer must be the one
    startup will give. Two validators would drift, and the way that drift shows
    up is a plugin that installs cleanly and then fails to load on the next
    launch, in a status table, with the folder already on disk.

    Raises `PluginError` naming the offending field.
    """
    try:
        document = tomlkit.parse(manifest.read_text(encoding="utf-8"))
    except Exception as error:
        raise PluginError(f"Invalid {LOCAL_MANIFEST}: {error}") from error

    raw_version = document.get("schema_version")
    raw_id = document.get("id")
    raw_module = document.get("module")
    raw_object = document.get("object", "plugin")
    if not isinstance(raw_version, int) or isinstance(raw_version, bool):
        raise PluginError("Manifest schema_version must be 1")
    schema_version = raw_version
    if schema_version != 1:
        raise PluginError(
            f"Unsupported manifest schema version {schema_version}; expected 1"
        )
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise PluginError("Manifest requires a non-empty string id")
    if not isinstance(raw_module, str) or not raw_module.strip():
        raise PluginError("Manifest requires a non-empty string module")
    if not isinstance(raw_object, str) or not raw_object.strip():
        raise PluginError("Manifest object must be a non-empty string")
    module = raw_module.strip()
    object_name = raw_object.strip()
    if not module.isidentifier():
        raise PluginError(
            "Manifest module must be a top-level Python module or package name"
        )
    if not object_name.isidentifier():
        raise PluginError("Manifest object must be a valid Python identifier")
    return LocalCandidate(
        plugin_id=raw_id.strip(),
        root=root,
        module=module,
        object_name=object_name,
    )


class PluginLoader:
    """Discover local and installed plugins and register valid definitions."""

    def __init__(
        self,
        manager: PluginManager,
        update_status: Callable[[str], None] | None = None,
        plugin_dir: Path | None = None,
        shipped_dir: Path | None = None,
        dev_dirs: Sequence[Path] | None = None,
    ) -> None:
        self.manager = manager
        self.update_status = update_status
        self.plugin_dir = plugin_dir or default_paths().plugins
        self.shipped_dir = shipped_dir
        # `is None` rather than falsy: an explicitly empty sequence means "no
        # development folders", which is not the same request as "work out
        # whether there are any", and anything constructing a loader for one
        # specific pair of directories has to be able to ask for the first while
        # a developer's variable is set in the environment around it.
        self.dev_dirs = tuple(dev_plugin_dirs() if dev_dirs is None else dev_dirs)
        self.failures: list[PluginLoadFailure] = []

    def load_plugins(self) -> PluginLoadReport:
        """Discover, validate, and register every available plugin.

        The user's own plugin directory is scanned first, sorted by casefolded
        directory name, then the examples shipped with the release, then
        installed `nfoforge.plugins` entry points, sorted by name. Registration
        is first-come-first-served: `PluginManager.register` rejects a second
        registration under an already-used plugin ID, so on an ID collision the
        plugin registered first wins and the later one fails with a duplicate-ID
        error, recorded as a load failure rather than applied silently.

        That ordering is deliberate at both boundaries. A local plugin beats an
        installed package because local plugins are the recommended installation
        method (see `docs/view/plugins/plugin-system.md`), and the user's own
        directory beats the shipped examples for the same reason: what the user
        put there must not be silently shadowed by something that arrived with a
        release.

        `dev_dirs` substitutes for the user's directory rather than adding to
        it, so none of the above changes when it is set -- only where the first
        group is read from. That is the point of replacing rather than layering:
        a development run resolves plugins by the rules a real installation
        uses, which is not true of an arrangement where two folders are live at
        once and a plugin can be picked up from a copy nobody remembered was
        there.

        Only the user's directory is created when missing, and not even that
        while development directories stand in for it -- a folder is not created
        to be ignored. The shipped directory lives inside the release, which is
        read-only territory, and a development directory either exists or is a
        mistake worth reporting.
        """

        self.failures.clear()
        self.manager.clear_load_issues()
        if not self.dev_dirs:
            try:
                self.plugin_dir.mkdir(exist_ok=True, parents=True)
            except OSError as error:
                self._record_failure(str(self.plugin_dir), error)
                return PluginLoadReport(self.manager.records, tuple(self.failures))

        for root in self._local_roots():
            manifest = root / LOCAL_MANIFEST
            if not manifest.is_file():
                continue
            try:
                candidate = read_local_manifest(root, manifest)
                self._notify(f"Loading plugin: {candidate.plugin_id}")
                definition = self._load_local_definition(candidate)
                self.manager.register(
                    candidate.plugin_id, definition, str(candidate.root)
                )
            except SystemExit as error:
                self._record_failure(
                    str(root), PluginError(f"Plugin exited during import: {error}")
                )
            except Exception as error:
                self._record_failure(str(root), error)

        for entry_point in self._entry_points():
            try:
                self._notify(f"Loading plugin: {entry_point.name}")
                definition = entry_point.load()
                if not isinstance(definition, PluginDefinition):
                    raise PluginError(
                        "Entry point must resolve to a PluginDefinition object"
                    )
                self.manager.register(
                    entry_point.name,
                    definition,
                    f"entry point {entry_point.value}",
                )
            except SystemExit as error:
                self._record_failure(
                    f"entry point {entry_point.name}",
                    PluginError(f"Plugin exited during import: {error}"),
                )
            except Exception as error:
                self._record_failure(f"entry point {entry_point.name}", error)

        if self.manager.records:
            loaded = ", ".join(record.plugin_id for record in self.manager.records)
            LOG.debug(LOG.LOG_SOURCE.FE, f"Detected plugins: {loaded}")
        return PluginLoadReport(self.manager.records, tuple(self.failures))

    def _checked_dev_dirs(self) -> list[Path]:
        """The development directories that are plugins folders, reporting the rest.

        A plugins folder that is empty, or missing, is a normal thing for a real
        installation to have and is passed over in silence. A development
        directory is a path someone typed into an environment variable, and it
        has taken the real folder out of the run, so the same silence would
        leave them with no plugins at all and nothing anywhere saying why.

        Both likely mistakes are named rather than left to be inferred. One is a
        path that is simply wrong. The other is naming a plugin where a folder
        of plugins belongs -- easy to do, since the plugin is the thing being
        worked on -- and it is recognisable, because that directory holds the
        manifest that should have been one level further down.
        """
        directories: list[Path] = []
        for directory in self.dev_dirs:
            if not directory.is_dir():
                self._record_failure(
                    str(directory),
                    PluginError(
                        f"{DEV_PLUGINS_ENV_VAR} names a path that is not a directory"
                    ),
                )
                continue
            if (directory / LOCAL_MANIFEST).is_file():
                self._record_failure(
                    str(directory),
                    PluginError(
                        f"{DEV_PLUGINS_ENV_VAR} entries are each a folder *of* "
                        f"plugins, not a plugin. This one holds {LOCAL_MANIFEST} "
                        "itself, so name the folder that contains it instead."
                    ),
                )
                continue
            if not declared_plugins(directory):
                self._record_failure(
                    str(directory),
                    PluginError(
                        f"{DEV_PLUGINS_ENV_VAR} names a directory holding no "
                        f"plugins. Each plugin is one folder inside it, holding "
                        f"{LOCAL_MANIFEST}."
                    ),
                )
                continue
            directories.append(directory)
        return directories

    def _local_roots(self) -> list[Path]:
        """Candidate plugin directories, the user's own first.

        Each directory is sorted by casefolded name so load order does not
        depend on the filesystem, and the groups are concatenated rather than
        merged and re-sorted, which is what makes the user's copy win a
        collision.

        Development directories stand in for the user's own rather than joining
        it, so the shape of this list does not change when they are set. Several
        of them are read in the order they were written, which is the only
        non-arbitrary answer available when two of them hold the same plugin id.
        """
        user_dirs = self._checked_dev_dirs() if self.dev_dirs else [self.plugin_dir]
        roots: list[Path] = []
        for directory in (*user_dirs, self.shipped_dir):
            if directory is None or not directory.is_dir():
                continue
            roots.extend(
                sorted(
                    (item for item in directory.iterdir() if item.is_dir()),
                    key=lambda item: item.name.casefold(),
                )
            )
        return roots

    @staticmethod
    def _load_local_definition(candidate: LocalCandidate) -> PluginDefinition:
        existing = sys.modules.get(candidate.module)
        if existing is not None:
            module_file = getattr(existing, "__file__", None)
            if module_file is None or not PluginLoader._is_below(
                Path(module_file), candidate.root
            ):
                raise PluginError(
                    f"Module name '{candidate.module}' is already loaded from "
                    "a different location"
                )
            module = existing
        else:
            spec = machinery.PathFinder.find_spec(
                candidate.module, [str(candidate.root)]
            )
            if spec is None or spec.loader is None or spec.origin is None:
                raise PluginError(
                    f"Could not find local plugin module '{candidate.module}'"
                )
            if not PluginLoader._is_below(Path(spec.origin), candidate.root):
                raise PluginError(
                    f"Plugin module '{candidate.module}' resolved outside its root"
                )

            module = util.module_from_spec(spec)
            sys.modules[candidate.module] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(candidate.module, None)
                raise

        definition: Any = getattr(module, candidate.object_name, None)
        if not isinstance(definition, PluginDefinition):
            raise PluginError(
                f"'{candidate.module}:{candidate.object_name}' must export a "
                "PluginDefinition"
            )
        return definition

    @staticmethod
    def _entry_points() -> Iterable[metadata.EntryPoint]:
        return tuple(
            sorted(
                metadata.entry_points(group=ENTRY_POINT_GROUP),
                key=lambda item: item.name,
            )
        )

    @staticmethod
    def _is_below(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError:
            return False
        return True

    def _notify(self, message: str) -> None:
        if self.update_status is not None:
            self.update_status(message)

    def _record_failure(self, source: str, error: Exception) -> None:
        failure = PluginLoadFailure(source, str(error) or type(error).__name__)
        self.failures.append(failure)
        self.manager.record_load_issue(failure.source, failure.reason)
        LOG.error(
            LOG.LOG_SOURCE.FE,
            f"Failed to load plugin '{source}':\n{traceback.format_exc()}",
        )
