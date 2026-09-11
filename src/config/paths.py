from dataclasses import dataclass
from os import environ
from pathlib import Path
import sys

from platformdirs import user_data_dir

from src.backend.utils.working_dir import IS_FROZEN, RUNTIME_DIR, asset_root

DATA_DIR_ENV_VAR = "NFOFORGE_DATA_DIR"
"""Redirects the state root. A test hook, not a supported feature."""


@dataclass(frozen=True)
class AppPaths:
    """Every location the application owns, derived from two roots.

    `state_root` is where files the user owns live, and `asset_root` is where
    files shipped with the release live. Keeping them apart is what makes a
    release folder replaceable.

    Paths are properties rather than fields with defaults. The previous form
    computed its defaults as class attributes at import time from `Path.cwd()`,
    which meant resolution depended on where the process was launched from and
    nothing could be reconfigured afterwards -- a throwaway tree had to be
    assembled by naming five paths by hand.

    The attribute names are deliberately unchanged. Plugins read
    `config.paths.user_configs` and derive their own storage from it, and those
    plugins are user-installed and sometimes compiled, so this release cannot
    patch them. Renaming would break them loudly; repointing a name while
    keeping it would break them silently, which is worse.
    """

    state_root: Path
    asset_root: Path

    @property
    def config_dir(self) -> Path:
        return self.state_root / "config"

    @property
    def default_config(self) -> Path:
        return self.asset_root / "config" / "defaults" / "default_config.toml"

    @property
    def default_program(self) -> Path:
        return self.asset_root / "config" / "defaults" / "default_program_conf.toml"

    @property
    def audio_conventions(self) -> Path:
        return self.asset_root / "config" / "audio_conventions"

    @property
    def program(self) -> Path:
        return self.config_dir / "program" / "conf.toml"

    @property
    def user_configs(self) -> Path:
        return self.config_dir / "user"

    @property
    def plugin_configs(self) -> Path:
        """Where plugins keep their own configuration and credentials.

        Plugins do not ask for this path, they compute it as
        `paths.user_configs.parent / "plugins"`. That makes it a derived
        location this code does not get to move independently: reparenting
        `user_configs` would silently orphan every plugin's credentials. The
        test asserting these two agree is the lock on that.
        """
        return self.config_dir / "plugins"

    @property
    def tracker_cookies(self) -> Path:
        return self.state_root / "cookies"

    @property
    def templates(self) -> Path:
        return self.state_root / "templates"

    @property
    def logs(self) -> Path:
        return self.state_root / "logs"

    @property
    def fonts(self) -> Path:
        return self.asset_root / "fonts"

    @property
    def images(self) -> Path:
        return self.asset_root / "images"

    @property
    def svg(self) -> Path:
        return self.asset_root / "svg"

    @property
    def docs(self) -> Path:
        return self.asset_root / "docs"

    @staticmethod
    def data_root() -> Path:
        """NfoForge's own per-user directory, and nothing above it.

        Named separately from `default_working_dir` because the two are the
        same path only for as long as the working directory defaults to the
        root of this directory. Cleanup asks for this one: it needs to know
        what it must never be able to delete, which is not the same question
        as where a run's output goes.
        """
        return Path(user_data_dir(appname="nfoforge", appauthor=False))

    @staticmethod
    def default_working_dir(ensure_exists: bool = False) -> Path:
        path = AppPaths.data_root()
        if ensure_exists:
            path.mkdir(parents=True, exist_ok=True)
        return path


ConfigPaths = AppPaths
"""The name plugins and existing tests hold. Same class, so neither can drift."""


def _override_allowed() -> bool:
    """Whether `NFOFORGE_DATA_DIR` is honoured in this process.

    Honoured from source and in the debug executable, so the migration can be
    rehearsed against a copy of a real install rather than only against
    synthesised fixtures. Refused by a released build, where an environment
    variable must not be able to decide where someone's profiles and
    credentials are read from and written to.
    """
    if not IS_FROZEN:
        return True
    return "debug" in Path(sys.executable).name.casefold()


def default_paths() -> AppPaths:
    """The roots this process actually runs against."""
    state_root = RUNTIME_DIR
    override = environ.get(DATA_DIR_ENV_VAR, "").strip()
    if override and _override_allowed():
        state_root = Path(override)
    return AppPaths(state_root=state_root, asset_root=asset_root())
