"""Shared construction and inspection helpers for config-manager tests.

Kept out of a `test_*.py` module so pytest does not collect it, and imported
fully-qualified (`from tests.test_config.config_tree import ...`) so it resolves
regardless of the working directory.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.config.paths import ConfigPaths
from tests.repo_paths import DEFAULT_CONFIG_DIR


def build_config_paths(tmp_path: Path) -> ConfigPaths:
    """A throwaway config tree seeded with the real packaged defaults."""
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    default_config = defaults / "default_config.toml"
    default_program = defaults / "default_program_conf.toml"
    default_config.write_text(
        (DEFAULT_CONFIG_DIR / "default_config.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    default_program.write_text(
        (DEFAULT_CONFIG_DIR / "default_program_conf.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return ConfigPaths(
        default_config=default_config,
        default_program=default_program,
        program=tmp_path / "program/conf.toml",
        user_configs=tmp_path / "user",
        tracker_cookies=tmp_path / "cookies",
    )


def leaf_key_paths(document: Mapping[str, Any], prefix: str = "") -> set[str]:
    """Every dotted leaf-key path in a parsed TOML document."""
    paths: set[str] = set()
    for key, value in document.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            paths |= leaf_key_paths(value, path)
        else:
            paths.add(path)
    return paths
