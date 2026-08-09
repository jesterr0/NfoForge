"""Cheap, read-only discovery of config profiles.

Listing saved jobs has to look in every profile's working directory, because
`working_dir` is a per-profile setting. Going through `ConfigManager` for that
would be far too heavy: it validates the schema, runs migrations, and rewrites
the file on disk. A profile the user hasn't opened in a while might legitimately
fail any of that, and a job picker must not be taken down by an unrelated
profile it merely wanted a path from.

So this reads the one key it needs straight out of the TOML and treats every
failure as "skip this profile". No validation, no migration, no writes.

Deliberately free of Qt imports so it stays unit testable.
"""

from __future__ import annotations

from pathlib import Path

import tomlkit
from tomlkit.exceptions import TOMLKitError

from src.config.paths import ConfigPaths
from src.logger.nfo_forge_logger import LOG

PROFILE_SUFFIX = ".toml"


def profile_working_dir(profile_path: Path) -> Path | None:
    """Read just `[general] working_dir` from a profile, or None if unreadable."""
    try:
        document = tomlkit.parse(profile_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TOMLKitError) as error:
        LOG.warning(
            LOG.LOG_SOURCE.BE,
            f"Could not read working directory from profile '{profile_path}': {error}",
        )
        return None

    general = document.get("general")
    if not isinstance(general, dict):
        return None
    working_dir = general.get("working_dir")
    if not isinstance(working_dir, str) or not working_dir.strip():
        return None
    return Path(working_dir)


def profile_working_dirs(paths: ConfigPaths | None = None) -> dict[str, Path]:
    """Map every profile name to the working directory it declares.

    A profile that declares nothing usable falls back to the same default
    `ConfigManager` would have given it, so its jobs are still found.
    """
    config_paths = paths or ConfigPaths()
    fallback = ConfigPaths.default_working_dir()

    discovered: dict[str, Path] = {}
    try:
        profile_paths = sorted(config_paths.user_configs.glob(f"*{PROFILE_SUFFIX}"))
    except OSError as error:
        LOG.warning(LOG.LOG_SOURCE.BE, f"Could not list config profiles: {error}")
        return discovered

    for profile_path in profile_paths:
        discovered[profile_path.stem] = profile_working_dir(profile_path) or fallback
    return discovered


def unique_working_dirs(paths: ConfigPaths | None = None) -> list[Path]:
    """Every distinct working directory across all profiles.

    Profiles commonly share one working directory, so the same folder must not
    be scanned (and its jobs listed) more than once.
    """
    seen: dict[Path, None] = {}
    for working_dir in profile_working_dirs(paths).values():
        seen.setdefault(working_dir, None)
    return list(seen)
