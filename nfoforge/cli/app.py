"""Bringing up enough of NfoForge to run from a terminal.

The desktop app does this across a splash screen, a worker thread and several
dialogs. What matters -- choose a profile, load it, load plugins -- is Qt-free
already; this is those steps in order, with failures raised as messages
instead of shown.
"""

from __future__ import annotations

from collections.abc import Callable

from nfoforge.backend.utils.working_dir import IS_FROZEN
from nfoforge.config.config import ConfigManager
from nfoforge.config.layout_version import LayoutRecordError, migration_pending
from nfoforge.config.paths import default_paths
from nfoforge.exceptions import ConfigError, ProfileMigrationRequired
from nfoforge.launcher import CLI_EXECUTABLE
from nfoforge.plugins.loader import PluginLoader

PROGRAM = CLI_EXECUTABLE if IS_FROZEN else "nfoforge"
"""What the user typed to run this, for usage and the hints printed."""


class CliError(Exception):
    """A problem to report as a message rather than a traceback."""


def available_profiles() -> list[str]:
    config_dir = default_paths().user_configs
    if not config_dir.is_dir():
        return []
    return sorted(path.stem for path in config_dir.glob("*.toml"))


def choose_profile(name: str | None) -> str:
    """The profile to load, or why one cannot be chosen.

    The desktop app puts a chooser on screen when several exist. A terminal
    does not guess instead: which tracker credentials a release is uploaded
    with is not a choice to make on someone's behalf.
    """
    profiles = available_profiles()
    if name:
        name = name.removesuffix(".toml")
        if name not in profiles:
            listing = ", ".join(profiles) or "none"
            raise CliError(f"No profile named {name!r} (profiles: {listing})")
        return name
    if len(profiles) == 1:
        return profiles[0]
    if not profiles:
        raise CliError(
            f"No config profile exists yet. Create one with: {PROGRAM} setup"
        )
    raise CliError(
        "Several config profiles exist; choose one with --config: "
        + ", ".join(profiles)
    )


def load_config(
    profile: str | None, warn: Callable[[str], None] = lambda _message: None
) -> ConfigManager:
    """Load a profile read-only, with its plugins.

    Read-only because the desktop app may have the same profile open, and
    nothing locks the file. A data folder the desktop app still has to migrate
    is refused rather than migrated from here.
    """
    # named in both messages: a source checkout and a release use different
    # data folders, so "the data folder" alone does not say which one
    state_root = default_paths().state_root
    try:
        if migration_pending(state_root):
            raise CliError(
                f"NfoForge's data folder ({state_root}) needs a one-time "
                f"migration. Run it with: {PROGRAM} setup"
            )
    except LayoutRecordError as error:
        raise CliError(
            f"NfoForge's data folder record ({state_root}) cannot be read: {error}"
        ) from error

    try:
        config = ConfigManager(choose_profile(profile), read_only=True)
    except ProfileMigrationRequired as error:
        raise CliError(f"{error} Upgrade it with: {PROGRAM} setup") from error
    except ConfigError as error:
        raise CliError(str(error)) from error

    if config.settings.general.enable_plugins:
        report = PluginLoader(
            config.plugin_manager,
            lambda _message: None,
            plugin_dir=config.paths.plugins,
            shipped_dir=config.paths.plugin_examples,
        ).load_plugins()
        for failure in report.failures:
            warn(f"plugin not loaded: {failure}")
    return config
