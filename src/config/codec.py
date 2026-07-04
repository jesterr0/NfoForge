from collections.abc import Mapping, MutableMapping
from typing import Any, TypeVar

import tomlkit

from src.config.models import AppConfig
from src.exceptions import ConfigError

TomlMutableMapping = TypeVar("TomlMutableMapping", bound=MutableMapping[str, Any])


class TomlConfigCodec:
    """Document-level TOML schema utilities used by the typed config manager."""

    SCHEMA_VERSION = 1

    @classmethod
    def validate_schema(cls, document: Mapping[str, Any]) -> None:
        version = int(document.get("schema_version", cls.SCHEMA_VERSION))
        if version != cls.SCHEMA_VERSION:
            raise ConfigError(f"Unsupported configuration schema_version: {version}")

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

    @staticmethod
    def dumps(document: Mapping[str, Any]) -> str:
        return tomlkit.dumps(document)

    @staticmethod
    def validate_settings(config: AppConfig) -> None:
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
            if type(actual_value) is not type(expected_value):
                raise ConfigError(
                    f"Invalid type at {path}: expected "
                    f"{type(expected_value).__name__}, got "
                    f"{type(actual_value).__name__}"
                )
