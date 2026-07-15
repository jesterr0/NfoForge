from collections.abc import MutableMapping
from datetime import datetime
from pathlib import Path
from typing import Any

import tomlkit

from src.config.codec import TomlConfigCodec
from src.config.dependencies import FindDependencies
from src.config.migrations import migrate_unversioned_to_v2
from src.config.models import AppConfig, ProgramConfig
from src.config.operations import TypedTomlOperations
from src.config.paths import ConfigPaths
from src.config.persistence import atomic_write_text
from src.config.registry import PluginRegistry
from src.exceptions import ConfigError, ConfigSchemaError

# TODO: add cryptography


class ConfigManager(TypedTomlOperations):
    """
    Parse config file and create a payload object to be used throughout
    the program as needed as well as store other payloads that might need shared
    """

    DEV_MODE: bool = False

    QBIT_SPECIFIC = ("category", "super_seeding")

    DELUGE_SPECIFIC = ("label", "path")

    RTORRENT_SPECIFIC = ("label", "path")

    TRANSMISSION_SPECIFIC = ("label", "path")

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
        # load various directories as needed
        self.paths.tracker_cookies.mkdir(exist_ok=True, parents=True)

        self.plugin_registry = PluginRegistry()

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
        default_text = self.paths.default_program.read_text(encoding="utf-8")
        if self.paths.program.exists():
            loaded = tomlkit.parse(self.paths.program.read_text(encoding="utf-8"))
            self._program_conf_toml_data = self.codec.merge_defaults(
                loaded, tomlkit.parse(default_text)
            )
        else:
            self._program_conf_toml_data = tomlkit.parse(default_text)
        if config_file:
            self._program_conf_toml_data["current_config"] = config_file
        self.decode_program()
        self.save_program()

    def decode_program(self) -> None:
        data = self._program_conf_toml_data
        self.program.current_config = data.get("current_config", "config")
        self.program.main_window_position = data.get("main_window_position")

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

            serialized = self.codec.dumps(self._program_conf_toml_data)
            if serialized != self._program_snapshot:
                atomic_write_text(self.paths.program, serialized)
                self._program_snapshot = serialized

        except Exception as e:
            raise ConfigError(f"Error saving program conf file: {str(e)}")

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
        default_toml = self.paths.default_config.read_text()
        self._default_document = tomlkit.parse(default_toml)
        self.codec.validate_schema(self._default_document)
        self.codec.validate_types(self._default_document, self._default_document)

        # update default config if not updated
        if not hasattr(self, "defaults"):
            self.decode(self._default_document, build_defaults=True)

        if config_path.exists():
            loaded_text = config_path.read_text(encoding="utf-8")
            loaded_document = tomlkit.parse(loaded_text)

            if "schema_version" not in loaded_document:
                migrated_document = self._try_migrate_unversioned_profile(
                    loaded_document, default_toml
                )
                if migrated_document is not None:
                    loaded_text = self.codec.dumps(migrated_document)
                    atomic_write_text(config_path, loaded_text)
                    # re-parse so downstream merge/validate/decode operate on
                    # a real TOML document, consistent with the normal
                    # (non-migration) load path
                    loaded_document = tomlkit.parse(loaded_text)

            self._config_snapshot = loaded_text
            try:
                self.codec.validate_schema(loaded_document)
            except ConfigSchemaError as error:
                if not error.config_path:
                    error.config_path = config_path
                raise
            self._toml_data = self.codec.merge_defaults(
                loaded_document,
                tomlkit.parse(default_toml),
            )
            self.codec.validate_types(self._toml_data, self._default_document)
            self.decode(self._toml_data)
            self.save(config_path)
        else:
            atomic_write_text(config_path, default_toml)
            self._toml_data = tomlkit.parse(default_toml)
            self.decode(self._toml_data)
            self._config_snapshot = default_toml
        self._active_profile_path = config_path
        # only update the active profile name once loading has fully
        # succeeded -- otherwise a profile that fails schema validation
        # (raising `ConfigSchemaError` above) would get persisted as
        # `current_config` even though it was never actually loaded
        if config_file:
            self.program.current_config = config_file

    def _try_migrate_unversioned_profile(
        self,
        loaded_document: MutableMapping[str, Any],
        default_toml: str,
    ) -> MutableMapping[str, Any] | None:
        """Attempt to migrate an unversioned ("schema 1") profile to schema 2.

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
            migrated_document, unmapped = migrate_unversioned_to_v2(
                loaded_document, self._default_document
            )
        except Exception:
            return None
        if unmapped:
            return None

        try:
            trial_document = tomlkit.parse(self.codec.dumps(migrated_document))
            self.codec.validate_schema(trial_document)
            merged_trial = self.codec.merge_defaults(
                trial_document, tomlkit.parse(default_toml)
            )
            self.codec.validate_types(merged_trial, self._default_document)
            self.decode(merged_trial, dry_run=True)
        except Exception:
            return None

        return migrated_document

    def save_as(self, save_path: Path) -> None:
        """Save the current settings under a new profile name."""
        self.program.current_config = save_path.stem
        self.save(save_path)
        self.save_program()

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

        config_path.replace(backup_path)
        atomic_write_text(
            config_path,
            config_paths.default_config.read_text(encoding="utf-8"),
        )
        return backup_path

    def _init_dependencies(self) -> None:
        """Initialize dependencies and updates the config if needed"""
        FindDependencies().update_dependencies(self.settings.dependencies)
