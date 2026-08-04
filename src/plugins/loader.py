from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import machinery, metadata, util
from pathlib import Path
import sys
import traceback
from typing import Any

import tomlkit

from src.backend.utils.working_dir import CURRENT_DIR
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
class _LocalCandidate:
    plugin_id: str
    root: Path
    module: str
    object_name: str


class PluginLoader:
    """Discover local and installed plugins and register valid definitions."""

    def __init__(
        self,
        manager: PluginManager,
        update_status: Callable[[str], None] | None = None,
        plugin_dir: Path | None = None,
    ) -> None:
        self.manager = manager
        self.update_status = update_status
        self.plugin_dir = plugin_dir or CURRENT_DIR / "plugins"
        self.failures: list[PluginLoadFailure] = []

    def load_plugins(self) -> PluginLoadReport:
        """Discover, validate, and register every available plugin.

        Local plugin directories are scanned first, sorted by casefolded
        directory name, followed by installed `nfoforge.plugins` entry points,
        sorted by name. Registration is first-come-first-served: `PluginManager
        .register` rejects a second registration under an already-used plugin
        ID, so on an ID collision the plugin registered first wins and the
        later one fails with a duplicate-ID error, recorded as a load failure
        rather than applied silently. Because local directories are scanned
        before entry points, a local plugin always wins a collision against an
        installed package sharing its ID. This precedence is deliberate, not
        incidental: local plugins are the recommended installation method (see
        `docs/view/plugins/plugin-system.md`), so an installed package must not
        be able to silently shadow one.
        """

        self.failures.clear()
        self.manager.clear_load_issues()
        try:
            self.plugin_dir.mkdir(exist_ok=True, parents=True)
        except OSError as error:
            self._record_failure(str(self.plugin_dir), error)
            return PluginLoadReport(self.manager.records, tuple(self.failures))

        for root in sorted(
            (item for item in self.plugin_dir.iterdir() if item.is_dir()),
            key=lambda item: item.name.casefold(),
        ):
            manifest = root / LOCAL_MANIFEST
            if not manifest.is_file():
                continue
            try:
                candidate = self._read_local_manifest(root, manifest)
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

    @staticmethod
    def _read_local_manifest(root: Path, manifest: Path) -> _LocalCandidate:
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
        return _LocalCandidate(
            plugin_id=raw_id.strip(),
            root=root,
            module=module,
            object_name=object_name,
        )

    @staticmethod
    def _load_local_definition(candidate: _LocalCandidate) -> PluginDefinition:
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
