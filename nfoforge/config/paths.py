from dataclasses import dataclass
from os import environ, pathsep
from pathlib import Path
import sys

from platformdirs import user_data_dir

from nfoforge.backend.utils.working_dir import (
    IS_FROZEN,
    WORKSPACE_DIR_NAME,
    asset_root,
)

DATA_DIR_ENV_VAR = "NFOFORGE_DATA_DIR"
"""Redirects every root this module resolves, for development and rehearsal.

Honoured from source and by the debug executable, refused by a released build.
Point it at a *copy* of an installation to rehearse a migration against real
data; pointing it at the original defeats the purpose of rehearsing.
"""

DEV_PLUGINS_ENV_VAR = "NFOFORGE_DEV_PLUGINS"
"""Plugins folders to use *instead of* the one in the data directory.

Each entry is a folder of plugins, the same shape as the plugins folder it
replaces, so everything below it behaves as it does in a real installation --
one folder per plugin, each holding `nfoforge-plugin.toml`. Several are
separated by `os.pathsep`, the way `PATH` separates its own, for checkouts kept
in more than one place.

Replaces rather than adds, which is the rule `DATA_DIR_ENV_VAR` follows and for
the same reason. An override that left the real folder loading too would make
development a configuration that exists nowhere else: collisions that only
happen here, and a plugin that can be picked up from a copy the developer has
forgotten about. Pointed somewhere else, the loader is doing exactly what it
does in production.

Honoured from source and by the debug executable, refused by a released build,
which matters more here than it does for the data directory: a plugin is trusted
Python executed inside NfoForge's process, so an environment variable must not be
able to decide what a release imports.
"""


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
        """Program preferences. One file, no longer in a directory of its own."""
        return self.config_dir / "program.toml"

    @property
    def user_configs(self) -> Path:
        """The profiles directory, which the migration writes as `profiles`.

        The attribute keeps its old name because plugins hold it, but the
        directory is named for what is in it rather than for who owns it. The
        rename stays inside `config/` so that `user_configs.parent / "plugins"`
        -- which is how a plugin finds its own storage -- still resolves to the
        same place.
        """
        return self.config_dir / "profiles"

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
    def plugins(self) -> Path:
        """Plugins the user installed, which are theirs and survive a release.

        They used to sit beside the executable, which is why replacing a release
        meant reinstalling them, and why the shipped examples and the user's own
        plugins shared one directory with nothing to tell them apart.

        Still the answer to "where do installed plugins live" even while
        `DEV_PLUGINS_ENV_VAR` has the loader reading somewhere else. Installing
        writes here, and Settings names this folder, because this is where a
        plugin goes when the development variable is gone.
        """
        return self.state_root / "plugins"

    @property
    def tools(self) -> Path:
        """Optional executables the user places here themselves, one folder each.

        A documented extension point, so it belongs with the user's own state
        rather than beside the installed application: a hand-assembled
        toolchain must survive replacing a release.
        """
        return self.state_root / "tools"

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

    @property
    def plugin_examples(self) -> Path:
        """Example plugins shipped with the release, loaded read-only.

        They live here rather than in the directory the user installs into, so
        a release can update its own examples without touching anything the
        user put there, and so migration can tell the two apart.
        """
        return self.asset_root / "plugin_examples"

    @staticmethod
    def data_root() -> Path:
        """NfoForge's own per-user directory, and nothing above it.

        Forwards to `resolve_data_root` rather than asking platformdirs itself,
        so that the source/installed split and `NFOFORGE_DATA_DIR` reach every
        caller. This used to be the direct lookup, which meant neither applied
        here -- and this is the root the default working directory, the saved
        jobs and the index cache all derive from.
        """
        return resolve_data_root()

    @staticmethod
    def default_working_dir(ensure_exists: bool = False) -> Path:
        """Where a profile writes when it names no working directory of its own.

        The workspace inside the data directory, not the data directory itself.
        Saved jobs and run output live in the workspace, so returning the root
        would have the application looking for jobs beside them rather than in
        them, and writing run output into the root the migration just cleared.
        """
        path = AppPaths.data_root() / WORKSPACE_DIR_NAME
        if ensure_exists:
            path.mkdir(parents=True, exist_ok=True)
        return path


ConfigPaths = AppPaths
"""The name plugins and existing tests hold. Same class, so neither can drift."""


def overrides_allowed() -> bool:
    """Whether this process honours the development environment variables.

    Honoured from source and in the debug executable, so the migration can be
    rehearsed against a copy of a real install rather than only against
    synthesised fixtures, and so a plugin can be run from its working tree.
    Refused by a released build, where an environment variable must not be able
    to decide where someone's profiles and credentials are read from and written
    to, nor what Python the application imports.

    One gate for both variables rather than one each. They are the same question
    -- is this a development process -- and a release that refused one while
    honouring the other would be a release with a hole in it.
    """
    if not IS_FROZEN:
        return True
    return "debug" in Path(sys.executable).name.casefold()


def _override() -> Path | None:
    """The directory `NFOFORGE_DATA_DIR` names, if this process honours it.

    Every root consults this one function. An override that moved some of them
    and not others would be worse than none at all: a rehearsal pointed at a
    copy of a real installation would look isolated while still writing into
    the original.
    """
    value = environ.get(DATA_DIR_ENV_VAR, "").strip()
    if not value or not overrides_allowed():
        return None
    return Path(value)


def dev_plugin_dirs() -> tuple[Path, ...]:
    """The plugins folders `NFOFORGE_DEV_PLUGINS` names, in order.

    Non-empty means the plugins folder in the data directory is not read at all.
    That is the whole point: development should be the same arrangement as a
    real installation, sited somewhere else.

    Order is kept rather than sorted, because the variable is written by hand
    and two folders holding the same plugin id have to be resolved somehow --
    the one written first is the one meant.

    Empty segments are dropped so that a trailing separator, or a variable set to
    nothing at all, reads as "no development folders" rather than as the current
    directory, which is what `Path("")` would otherwise give. Nothing here checks
    that an entry exists or holds anything: that is the loader's to report,
    because it is the loader that can put the answer in front of the user.
    """
    if not overrides_allowed():
        return ()
    value = environ.get(DEV_PLUGINS_ENV_VAR, "")
    return tuple(Path(entry) for entry in value.split(pathsep) if entry.strip())


def resolve_data_root() -> Path:
    """NfoForge's own per-user directory for this process.

    A source run gets a different directory from an installed one, because a
    developer has both and they would otherwise share every profile, credential
    and saved job -- with the source run offering to migrate the data the
    installed copy is using. Isolating by default leaves no variable to
    remember and no way for forgetting one to reach real data.

    Named separately from `default_working_dir` because the two are the same
    path only for as long as the working directory defaults to the root of this
    directory. Cleanup asks for this one: it needs to know what it must never
    be able to delete, which is not the same question as where a run's output
    goes.
    """
    override = _override()
    if override is not None:
        return override
    appname = "nfoforge" if IS_FROZEN else "nfoforge-dev"
    return Path(user_data_dir(appname=appname, appauthor=False))


def default_paths() -> AppPaths:
    """The roots this process actually runs against.

    The state root is the per-user data directory, which is the move this whole
    exercise is for: a release folder can be replaced wholesale without touching
    anything the user owns. It was the mutable tree inside the installation,
    which is why replacing a release meant reconstructing a configuration.
    """
    return AppPaths(state_root=resolve_data_root(), asset_root=asset_root())
