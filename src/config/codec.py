from collections.abc import Mapping, MutableMapping
from typing import Any, TypeVar

import tomlkit

from src.config.models import AppConfig
from src.enums.torrent_client import QBittorrentSavePathMode
from src.exceptions import ConfigError, ConfigSchemaError

TomlMutableMapping = TypeVar("TomlMutableMapping", bound=MutableMapping[str, Any])


class TomlConfigCodec:
    """Document-level TOML schema utilities used by the typed config manager."""

    SCHEMA_VERSION = 12

    @classmethod
    def validate_schema(cls, document: Mapping[str, Any]) -> None:
        if "schema_version" not in document:
            raise ConfigSchemaError(
                "Missing configuration schema_version. "
                "Please generate a new config file."
            )
        raw_version = document["schema_version"]
        try:
            version = int(raw_version)
        except (TypeError, ValueError) as error:
            raise ConfigSchemaError(
                f"Invalid configuration schema_version: {raw_version!r}. "
                "Please generate a new config file."
            ) from error
        if version < cls.SCHEMA_VERSION:
            raise ConfigSchemaError(
                f"Unsupported configuration schema_version: {version}. "
                f"Expected schema_version: {cls.SCHEMA_VERSION}. "
                "Please generate a new config file."
            )
        if version > cls.SCHEMA_VERSION:
            raise ConfigSchemaError(
                f"Configuration schema_version {version} is newer than the "
                f"supported schema_version {cls.SCHEMA_VERSION}. This "
                "configuration file may be from a newer version of the "
                "application (e.g. after downgrading). Please generate a "
                "new config file or reinstall the application version that "
                "created it."
            )

    @classmethod
    def merge_defaults(
        cls,
        document: TomlMutableMapping,
        defaults: Mapping[str, Any],
    ) -> TomlMutableMapping:
        for key, value in defaults.items():
            if key not in document:
                document[key] = value
            elif isinstance(value, MutableMapping):
                current = document.get(key)
                if not isinstance(current, MutableMapping):
                    document[key] = value
                else:
                    cls.merge_defaults(current, value)
        return document

    @classmethod
    def coerce_bool_flags(
        cls,
        document: MutableMapping[str, Any],
        defaults: Mapping[str, Any],
    ) -> MutableMapping[str, Any]:
        """Coerce persisted ints to ``bool`` where the default declares a bool.

        Some boolean tracker flags (e.g. ``tracker.*.anonymous``) were shipped
        in the packaged default as the int ``0`` while the model, the UI (a
        ``QCheckBox``) and the write path all treat them as ``bool``. Once the
        app wrote such a value back from its own model it became a TOML
        ``true``/``false``, which `validate_types` -- which deliberately
        refuses to treat ``bool`` as ``int`` -- would then reject on the next
        load. The default now declares these as real booleans; this pass
        normalizes any lingering integer ``0``/``1`` (from an older default, a
        hand-edited profile, or a schema-1 migration that copied the tracker
        section forward verbatim) to ``bool`` so both representations converge
        on the default's type before `validate_types` runs. Non-0/1 integers
        are left untouched so genuinely bad values still surface as a type
        error rather than being silently coerced.
        """
        for key, expected in defaults.items():
            if key not in document:
                continue
            if isinstance(expected, MutableMapping):
                current = document.get(key)
                if isinstance(current, MutableMapping):
                    cls.coerce_bool_flags(current, expected)
                continue
            expected_value = (
                expected.unwrap() if hasattr(expected, "unwrap") else expected
            )
            actual = document[key]
            actual_value = actual.unwrap() if hasattr(actual, "unwrap") else actual
            if (
                type(expected_value) is bool
                and type(actual_value) is int  # excludes bool, an int subclass
                and actual_value in (0, 1)
            ):
                document[key] = bool(actual_value)
        return document

    @staticmethod
    def dumps(document: Mapping[str, Any]) -> str:
        return tomlkit.dumps(document)

    @staticmethod
    def validate_settings(config: AppConfig) -> None:
        qbit = config.torrent_clients.qbittorrent
        if (
            qbit.save_path_mode is QBittorrentSavePathMode.TEMPLATE
            and not qbit.save_path_template.strip()
        ):
            raise ConfigError(
                "Invalid configuration value at "
                "torrent_client.qbittorrent.specific_params.save_path_template"
            )

        checks = {
            "general.ui_scale_factor": config.general.ui_scale_factor > 0,
            "general.timeout": config.general.timeout > 0,
            "general.log_total": config.general.log_total >= 0,
            "screenshots.count": config.screenshots.count >= 0,
            "screenshots.trim_start": config.screenshots.trim_start >= 0,
            "screenshots.trim_end": config.screenshots.trim_end >= 0,
            "screenshots.min_required_selected": (
                config.screenshots.min_required_selected >= 0
            ),
            "screenshots.max_required_selected": (
                config.screenshots.max_required_selected >= 0
            ),
            "screenshots.optimize_downloaded_images_percentage": (
                0 < config.screenshots.optimize_downloaded_images_percentage <= 1
            ),
            "urls.columns": config.urls.columns >= 0,
            "urls.vertical": config.urls.vertical >= 0,
            "urls.horizontal": config.urls.horizontal >= 0,
            "urls.image_width": config.urls.image_width >= 0,
            "tracker.lst.free": 0 <= config.trackers.lst.free <= 100,
            "template_settings.newline_sequence": config.templates.newline_sequence
            in {"\n", "\r", "\r\n"},
        }
        for path, valid in checks.items():
            if not valid:
                raise ConfigError(f"Invalid configuration value at {path}")
        if (
            config.screenshots.max_required_selected
            and config.screenshots.min_required_selected
            > config.screenshots.max_required_selected
        ):
            raise ConfigError(
                "Invalid configuration value at screenshots.min_required_selected"
            )

    @classmethod
    def validate_types(
        cls,
        document: Mapping[str, Any],
        defaults: Mapping[str, Any],
        prefix: str = "",
    ) -> None:
        """Validate known values against the default document's TOML types."""
        for key, expected in defaults.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in document:
                raise ConfigError(f"Missing configuration key: {path}")
            actual = document[key]
            if isinstance(expected, MutableMapping):
                if not isinstance(actual, MutableMapping):
                    raise ConfigError(f"Expected table at {path}")
                cls.validate_types(actual, expected, path)
                continue
            expected_value = (
                expected.unwrap() if hasattr(expected, "unwrap") else expected
            )
            actual_value = actual.unwrap() if hasattr(actual, "unwrap") else actual
            if (
                type(expected_value) is float
                and isinstance(actual_value, int)
                and not isinstance(actual_value, bool)
            ):
                # an int is an acceptable value where a float is expected
                # (e.g. `ui_scale_factor = 1` for a default of `1.0`); `bool`
                # is excluded since it is a subclass of `int` in Python and
                # must still be rejected where a float/int is expected.
                continue
            if type(actual_value) is not type(expected_value):
                raise ConfigError(
                    f"Invalid type at {path}: expected "
                    f"{type(expected_value).__name__}, got "
                    f"{type(actual_value).__name__}"
                )
