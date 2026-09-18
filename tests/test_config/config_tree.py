"""Shared construction and inspection helpers for config-manager tests.

Kept out of a `test_*.py` module so pytest does not collect it, and imported
fully-qualified (`from tests.test_config.config_tree import ...`) so it resolves
regardless of the working directory.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.config.paths import ConfigPaths
from tests.repo_paths import build_app_paths


def build_config_paths(tmp_path: Path) -> ConfigPaths:
    """A throwaway config tree seeded with the real packaged defaults."""
    return build_app_paths(tmp_path)


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
