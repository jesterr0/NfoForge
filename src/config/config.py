from collections.abc import MutableMapping
from datetime import datetime
from pathlib import Path
import shutil
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError

from src.config.codec import TomlConfigCodec
from src.config.dependencies import FindDependencies
from src.config.migrations import document_version, migrate_document
from src.config.models import AppConfig, ProgramConfig
from src.config.operations import TypedTomlOperations
from src.config.paths import ConfigPaths
from src.config.persistence import atomic_write_text
from src.exceptions import ConfigError, ConfigSchemaError
from src.logger.nfo_forge_logger import LOG
from src.plugins.manager import PluginManager


class ConfigManager(TypedTomlOperations):
    """
    Parse config file and create a payload object to be used throughout
    the program as needed as well as store other payloads that might need shared
    """

    def __init__(
        self,
        config_file: str | None,
        paths: ConfigPaths | None = None,
    ):
        self.paths = paths or ConfigPaths()
        self.codec = TomlConfigCodec()
        self._program_snapshot: str | None = None
        self._config_snapshot: str | None = None
        self._active_profile_path: Path | None = None
        self._program_conf_toml_data: MutableMapping[str, Any]
        self._toml_data: MutableMapping[str, Any]
        self._default_document: MutableMapping[str, Any]
        self._migration_error: str | None = None
        # load various directories as needed
        self.paths.tracker_cookies.mkdir(exist_ok=True, parents=True)

        self.plugin_manager = PluginManager()

        # load program config
        self.program = ProgramConfig()
        self.load_program(config_file)

        # variables that are assigned during init
        self.settings: AppConfig
        self.defaults: AppConfig
        self.load_profile(config_file)

        # dependencies
        self._init_dependencies()

        # call save just in case some data is not up to date
        self.save()

    def load_program(self, config_file: str | None) -> None:
        """
        Loads program config, this will be small and only control very
        unique settings that doesn't belong in the main config.
        """
        _, default_document = self._read_toml(
            self.paths.default_program, "default program configuration"
        )
        if self.paths.program.exists():
            _, loaded = self._read_toml(self.paths.program, "program configuration")
            self._program_conf_toml_data = self.codec.merge_defaults(
                loaded, default_document
            )
        else:
            self._program_conf_toml_data = default_document
        if config_file:
            self._program_conf_toml_data["current_config"] = config_file
        self.decode_program()
        self.save_program()

    def decode_program(self) -> None:
        data = self._program_conf_toml_data
        self.program.current_config = data.get("current_config", "config")
        self.program.main_window_position = data.get("main_window_position")
        self.program.suppress_template_token_prompt = bool(
            data.get("suppress_template_token_prompt", False)
        )

    def save_program(self) -> None:
        """Converts config payload object to TOML and writes to a file"""
        try:
            # update the toml object
            self._program_conf_toml_data["current_config"] = (
                self.program.current_config if self.program.current_config else ""
            )
            self._program_conf_toml_data["main_window_position"] = (
                self.program.main_window_position
                if self.program.main_window_position
                else ""
            )
            self._program_conf_toml_data["suppress_template_token_prompt"] = (
                self.program.suppress_template_token_prompt
            )

            serialized = self.codec.dumps(self._program_conf_toml_data)
            if serialized != self._program_snapshot:
                atomic_write_text(self.paths.program, serialized)
                self._program_snapshot = serialized

        except Exception as e:
            raise ConfigError(f"Error saving program conf file: {str(e)}") from e

    def load_profile(self, config_file: str | None = None) -> None:
        """Loads config file, if missing automatically creates one from the example template."""
        if config_file:
            config_path = self.paths.user_configs / str(config_file + ".toml")
        else:
            if not self.program.current_config:
                raise ConfigError("Failure to load current config")
            config_path = self.paths.user_configs / str(
                self.program.current_config + ".toml"
            )

        # read default toml file
        default_toml, self._default_document = self._read_toml(
            self.paths.default_config, "default configuration"
        )
        self.codec.validate_schema(self._default_document)
        self.codec.validate_types(self._default_document, self._default_document)

        # update default config if not updated
        if not hasattr(self, "defaults"):
            self.decode(self._default_document, build_defaults=True)

        if config_path.exists():
            loaded_text, loaded_document = self._read_toml(
                config_path, "user configuration"
            )

            try:
                loaded_version: int | None = document_version(loaded_document)
            except (TypeError, ValueError):
                # A malformed `schema_version` (e.g. the string "two") is not
                # migratable. Leave it for `validate_schema` below, which
                # reports it as a `ConfigSchemaError` rather than letting a
                # bare ValueError escape to the global excepthook.
                loaded_version = None

            if (
                loaded_version is not None
                and loaded_version < self.codec.SCHEMA_VERSION
            ):
                self._migration_error = None
                migrated_document = self._try_migrate_profile(
                    loaded_document, default_toml
                )
                if migrated_document is not None:
                    self.archive_profile(config_path)
                    loaded_text = self.codec.dumps(migrated_document)
                    atomic_write_text(config_path, loaded_text)
                    # re-parse so downstream merge/validate/decode operate on
                    # a real TOML document, consistent with the normal
                    # (non-migration) load path
                    loaded_document = tomlkit.parse(loaded_text)
                else:
                    reason = self._migration_error or (
                        "the document could not be mapped to the current schema"
                    )
                    raise ConfigSchemaError(
                        f"Could not migrate configuration schema_version "
                        f"{loaded_version}: {reason}",
                        config_path=config_path,
                    )

            self._config_snapshot = loaded_text
            try:
                # Assigned atomically: only if the full validate/merge/decode
                # sequence succeeds. This is intentional -- if validation
                # fails at any step (schema, `validate_types`, or `decode`),
                # `self._toml_data` must NOT be reassigned, so it stays
                # consistent with `self.settings`, which is likewise only
                # ever updated on a fully successful `decode`. A failed
                # reload therefore leaves the previously-loaded profile's
                # state intact instead of mixing the new (invalid) document
                # with the old settings.
                self._toml_data = self._validate_document(loaded_document, default_toml)
            except ConfigSchemaError as error:
                if not error.config_path:
                    error.config_path = config_path
                raise
            # only update the active profile name once loading has fully
            # succeeded -- otherwise a profile that fails schema validation
            # (raising `ConfigSchemaError` above) would get persisted as
            # `current_config` even though it was never actually loaded.
            # This must happen *before* `self.save` below: `save()` calls
            # `save_program()`, which writes `self.program.current_config`
            # to disk, so the assignment has to land first or the on-disk
            # program-conf file keeps the stale profile name until some
            # later, unrelated save.
            if config_file:
                self.program.current_config = config_file
            self.save(config_path)
        else:
            atomic_write_text(config_path, default_toml)
            self._toml_data = tomlkit.parse(default_toml)
            self.decode(self._toml_data)
            self._config_snapshot = default_toml
            if config_file:
                self.program.current_config = config_file
        self._active_profile_path = config_path

    def _validate_document(
        self,
        document: MutableMapping[str, Any],
        default_toml: str,
        dry_run: bool = False,
    ) -> MutableMapping[str, Any]:
        """Run the validate/merge/decode sequence `load_profile` applies to
        a loaded profile: schema check, merge defaults (against a fresh
        parse of ``default_toml``), coerce legacy int 0/1 flags to bool where
        the default is a bool, per-key type validation against
        ``self._default_document``, then `decode` (which also runs
        `validate_settings`).

        Shared by `load_profile` (the real load, ``dry_run=False``) and
        `_try_migrate_profile`'s trial validation (``dry_run=True``, never
        persisted) so the two paths cannot drift apart if this sequence ever
        changes.

        Returns the defaults-merged document. Raises whatever the
        underlying steps raise (e.g. `ConfigSchemaError`, `ConfigError`) on
        failure.
        """
        self.codec.validate_schema(document)
        merged = self.codec.merge_defaults(document, tomlkit.parse(default_toml))
        # Normalize legacy integer 0/1 tracker flags to bool where the default
        # declares a bool, before per-key type validation. This self-heals both
        # a config the app previously wrote as a real bool (default now bool ->
        # no-op) and one still holding the old integer representation from a
        # hand-edited or earlier profile.
        self.codec.coerce_bool_flags(merged, self._default_document)
        self.codec.validate_types(merged, self._default_document)
        self.decode(merged, dry_run=dry_run)
        return merged

    def _try_migrate_profile(
        self,
        loaded_document: MutableMapping[str, Any],
        default_toml: str,
    ) -> MutableMapping[str, Any] | None:
        """Attempt to migrate an older profile up to the current schema.

        `migrate_document` applies every intermediate hop, so a profile
        several versions behind is carried through each shape in turn rather
        than being rejected.

        Returns the migrated document on success -- but only after proving it
        actually validates, by running it through the exact same validation
        `load_profile` applies to a normal, already-current-schema config:
        schema check, merge defaults, per-key type validation, and a decode
        (which also runs `validate_settings`). That trial run happens on an
        in-memory copy only (`decode(..., dry_run=True)`), never on the
        document that gets persisted, so a migration that maps structurally
        but produces an invalid document can't destroy the original file.

        Returns ``None`` if migration is not possible (some section could
        not be mapped), the migrated document fails validation, or anything
        raised, in which case the caller must leave the original
        document/file untouched and fall through to the normal
        `ConfigSchemaError` path so the existing archive+regenerate flow can
        take over.
        """
        try:
            migrated_document, unmapped = migrate_document(
                loaded_document, self._default_document
            )
        except Exception as error:
            self._migration_error = f"{type(error).__name__}: {error}"
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Configuration migration failed: {self._migration_error}",
            )
            return None
        if unmapped:
            self._migration_error = "unmapped sections: " + ", ".join(
                sorted(set(unmapped))
            )
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Configuration migration failed: {self._migration_error}",
            )
            return None

        try:
            trial_document = tomlkit.parse(self.codec.dumps(migrated_document))
            self._validate_document(trial_document, default_toml, dry_run=True)
        except Exception as error:
            self._migration_error = f"{type(error).__name__}: {error}"
            LOG.warning(
                LOG.LOG_SOURCE.BE,
                f"Configuration migration validation failed: {self._migration_error}",
            )
            return None

        return migrated_document

    def save_as(self, save_path: Path) -> None:
        """Save the current settings under a new profile name."""
        self.program.current_config = save_path.stem
        self.save(save_path)
        self.save_program()

    @staticmethod
    def _read_toml(
        path: Path, description: str
    ) -> tuple[str, MutableMapping[str, Any]]:
        """Read and parse a UTF-8 TOML document with a user-facing error."""
        try:
            text = path.read_text(encoding="utf-8")
            return text, tomlkit.parse(text)
        except (OSError, UnicodeError, ParseError) as error:
            raise ConfigError(
                f"Error reading {description} '{path}': {error}"
            ) from error

    @staticmethod
    def _backup_path(config_path: Path) -> Path:
        backup_dir = config_path.parent / "old_configs"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{config_path.stem}_{timestamp}{config_path.suffix}"
        counter = 1
        while backup_path.exists():
            backup_path = backup_dir / (
                f"{config_path.stem}_{timestamp}_{counter}{config_path.suffix}"
            )
            counter += 1
        return backup_path

    @classmethod
    def archive_profile(cls, config_path: Path) -> Path:
        """Copy a profile into ``old_configs`` before a lossy rewrite."""
        if not config_path.exists():
            raise ConfigError(f"Cannot archive missing config file: {config_path}")
        backup_path = cls._backup_path(config_path)
        try:
            shutil.copy2(config_path, backup_path)
        except OSError as error:
            raise ConfigError(f"Could not archive config file: {error}") from error
        return backup_path

    @classmethod
    def replace_profile_with_default(
        cls,
        config_path: Path,
        paths: ConfigPaths | None = None,
    ) -> Path:
        """Archive an incompatible profile and replace it with the default config."""
        config_paths = paths or ConfigPaths()
        if not config_path.exists():
            atomic_write_text(
                config_path,
                config_paths.default_config.read_text(encoding="utf-8"),
            )
            return config_path

        backup_path = cls._backup_path(config_path)
        config_path.replace(backup_path)
        atomic_write_text(
            config_path,
            config_paths.default_config.read_text(encoding="utf-8"),
        )
        return backup_path

    def _init_dependencies(self) -> None:
        """Initialize dependencies and updates the config if needed"""
        FindDependencies().update_dependencies(self.settings.dependencies)
