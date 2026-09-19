"""Coverage for the path object every other module asks for its locations.

Two roots go in and every path comes out of one of them. The old form bound
its paths as class attributes computed from `Path.cwd()` at import, which is
why a test that wanted a throwaway tree had to name five paths by hand and why
nothing could be reconfigured afterwards.
"""

from os import pathsep
from pathlib import Path
import sys

from platformdirs import user_data_dir
import pytest

from src.config.paths import (
    DATA_DIR_ENV_VAR,
    DEV_PLUGINS_ENV_VAR,
    AppPaths,
    ConfigPaths,
    default_paths,
    dev_plugin_dirs,
    resolve_data_root,
)


def test_config_paths_is_the_same_class(tmp_path: Path) -> None:
    """Plugins read `config.paths.user_configs`, and tests construct the class.

    Both are public surface held by code this release cannot patch, so the old
    name stays bound to the new class and the attribute names do not move. An
    alias that kept a name while changing what it pointed at would be worse
    than a rename, because nothing would fail loudly.
    """
    assert ConfigPaths is AppPaths


def test_state_paths_derive_from_the_state_root(tmp_path: Path) -> None:
    state = tmp_path / "state"
    paths = AppPaths(state_root=state, asset_root=tmp_path / "assets")

    assert paths.program == state / "config" / "program.toml"
    assert paths.user_configs == state / "config" / "profiles"
    assert paths.tracker_cookies == state / "cookies"


def test_packaged_defaults_derive_from_the_asset_root(tmp_path: Path) -> None:
    """The packaged defaults are shipped files, so they come from the assets.

    This is the split the whole refactor turns on: the defaults a release reads
    are read-only and travel with the build, while everything the user edits
    lives somewhere a release can be replaced without touching it.
    """
    assets = tmp_path / "assets"
    paths = AppPaths(state_root=tmp_path / "state", asset_root=assets)

    assert (
        paths.default_config == assets / "config" / "defaults" / "default_config.toml"
    )
    assert (
        paths.default_program
        == assets / "config" / "defaults" / "default_program_conf.toml"
    )


def test_every_path_sits_under_one_of_the_two_roots(tmp_path: Path) -> None:
    """No path may be left bound to somewhere neither root names.

    Walks the object rather than listing paths, so a property added later is
    covered without anyone remembering to extend this test.
    """
    state = tmp_path / "state"
    assets = tmp_path / "assets"
    paths = AppPaths(state_root=state, asset_root=assets)

    found = {
        name: value
        for name in dir(paths)
        if not name.startswith("_")
        and isinstance(value := getattr(paths, name, None), Path)
    }

    assert found, "no paths were discovered, so this test proves nothing"
    for name, value in found.items():
        assert value.is_relative_to(state) or value.is_relative_to(assets), (
            f"{name} resolves to {value}, which is under neither root"
        )


def test_the_state_root_is_the_per_user_data_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The move this whole exercise is for: user state leaves the install.

    A release folder can then be replaced wholesale without touching anything
    the user owns, which is the upgrade experience being bought. Asserted
    against platformdirs directly rather than against the function under test,
    so the two cannot agree on a wrong answer.
    """
    monkeypatch.setattr("src.config.paths.IS_FROZEN", False)
    monkeypatch.delenv(DATA_DIR_ENV_VAR, raising=False)

    assert default_paths().state_root == Path(
        user_data_dir(appname="nfoforge-dev", appauthor=False)
    )


def test_a_released_build_puts_state_in_its_own_per_user_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """And the shipped build uses the real one, not the development directory."""
    monkeypatch.setattr("src.config.paths.IS_FROZEN", True)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "NfoForge.exe"))
    monkeypatch.delenv(DATA_DIR_ENV_VAR, raising=False)

    assert default_paths().state_root == Path(
        user_data_dir(appname="nfoforge", appauthor=False)
    )


def test_the_data_directory_override_is_honoured_from_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The override exists so a real migration can be rehearsed.

    Running from source has to honour it, or development after the state move
    reads and writes the same per-user directory as an installed copy, and a
    dev run would offer to migrate a working tree into it.
    """
    monkeypatch.setattr("src.config.paths.IS_FROZEN", False)
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path / "rehearsal"))

    assert default_paths().state_root == tmp_path / "rehearsal"


def test_the_override_is_refused_by_a_released_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shipped executable must not let the environment move user data.

    Otherwise anything that can set a variable in the process environment
    decides where profiles, cookies and credentials are read from.
    """
    monkeypatch.setattr("src.config.paths.IS_FROZEN", True)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "NfoForge.exe"))
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path / "rehearsal"))

    assert default_paths().state_root == Path(
        user_data_dir(appname="nfoforge", appauthor=False)
    )


def test_the_override_is_honoured_by_the_debug_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A release ships a debug executable beside the main one.

    That is the one a rehearsal runs, so the migration can be exercised on the
    artefact that actually ships rather than only from source.
    """
    monkeypatch.setattr("src.config.paths.IS_FROZEN", True)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "NfoForge-debug.exe"))
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path / "rehearsal"))

    assert default_paths().state_root == tmp_path / "rehearsal"


def test_running_from_source_gets_its_own_per_user_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source run must not share the directory an installed copy uses.

    Both resolve the same per-user location today, so once user state moves
    there a source run reads and writes the same profiles, credentials and
    saved jobs as the release the developer also has installed -- and offers to
    migrate them. Isolating by default means there is no variable to remember,
    and forgetting one cannot reach someone's working data.
    """
    monkeypatch.setattr("src.config.paths.IS_FROZEN", False)
    monkeypatch.delenv(DATA_DIR_ENV_VAR, raising=False)

    resolved = resolve_data_root()

    assert resolved != Path(user_data_dir(appname="nfoforge", appauthor=False))
    assert resolved.name == "nfoforge-dev"


def test_the_override_redirects_the_per_user_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One variable has to move every location, not just the state root.

    A rehearsal points this at a copy of a real installation, and the point of
    doing that is that nothing escapes to the original. The per-user directory
    is where the default working directory, the saved jobs and the index cache
    resolve from, so an override that moved the state root and left this behind
    would rehearse the migration while writing into live data.
    """
    monkeypatch.setattr("src.config.paths.IS_FROZEN", False)
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path / "rehearsal"))

    assert resolve_data_root() == tmp_path / "rehearsal"
    assert default_paths().state_root == tmp_path / "rehearsal"


def test_the_per_user_directory_ignores_the_override_in_a_released_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same reasoning as the state root: the environment must not move real data.

    This one matters more, because it is the directory holding saved jobs.
    """
    monkeypatch.setattr("src.config.paths.IS_FROZEN", True)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "NfoForge.exe"))
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path / "rehearsal"))

    assert resolve_data_root() == Path(
        user_data_dir(appname="nfoforge", appauthor=False)
    )


def test_no_test_can_reach_the_real_per_user_directory(tmp_path: Path) -> None:
    """The suite must not be able to touch the directory a real install uses.

    `data_root` is not a passive lookup. `ConfigOperations` calls
    `default_working_dir(ensure_exists=True)` for any configuration with no
    explicit working directory, which creates whatever it resolves to, and the
    per-user directory is where a real install keeps its saved jobs, its index
    cache and its run output. A test that reached it would be writing into
    someone's working data.

    Neither the `AppPaths` instance under test nor `NFOFORGE_DATA_DIR` prevents
    that on its own, because this resolves through a static method that consults
    neither. So the suite sandboxes it for every test, and this asserts the
    sandbox is in place -- without calling `ensure_exists`, which on a broken
    sandbox would create the very directory being guarded.
    """
    sandboxed = AppPaths.data_root()

    assert sandboxed != Path(user_data_dir(appname="nfoforge", appauthor=False))
    assert sandboxed.is_relative_to(tmp_path), (
        f"data_root() resolved to {sandboxed}, outside this test's tmp_path"
    )


def test_a_blank_override_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty or whitespace value is an unset variable, not the filesystem root."""
    monkeypatch.setattr("src.config.paths.IS_FROZEN", False)
    monkeypatch.setenv(DATA_DIR_ENV_VAR, "   ")

    assert default_paths().state_root == Path(
        user_data_dir(appname="nfoforge-dev", appauthor=False)
    )


def test_the_config_layout_matches_where_migration_puts_things(tmp_path: Path) -> None:
    """These two names have to agree with the migration, or nothing is found.

    The migration copies a previous installation's program preferences to
    `config/program.toml` and its profiles to `config/profiles`. Read the old
    locations instead and a migrated installation starts with no preferences and
    no profiles, having successfully moved both.

    The nesting the old names carried is gone on purpose: `config/program/` was a
    directory holding one file, and `user` said who owned the directory rather
    than what was in it.
    """
    state = tmp_path / "state"
    paths = AppPaths(state_root=state, asset_root=tmp_path / "assets")

    assert paths.program == state / "config" / "program.toml"
    assert paths.user_configs == state / "config" / "profiles"


def test_plugin_storage_still_derives_from_the_profiles_path(tmp_path: Path) -> None:
    """Plugins compute their own storage, so moving profiles must not move it.

    A plugin asks for `paths.user_configs.parent / "plugins"` rather than being
    handed a path, and plugins are user-installed and sometimes compiled, so this
    release cannot patch them. Renaming the profiles directory changes what that
    expression resolves to unless the parent stays put -- which is the whole
    reason the rename happened inside `config/` rather than above it.
    """
    paths = AppPaths(state_root=tmp_path / "state", asset_root=tmp_path / "assets")

    assert paths.user_configs.parent / "plugins" == paths.plugin_configs


def test_the_default_working_directory_is_the_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same fault as a stale setting, in its no-setting form.

    A profile with no working directory of its own falls back to this, and the
    new layout keeps run output and saved jobs inside the workspace. Returning
    the data directory root instead would have the application looking for jobs
    beside the workspace rather than in it, and writing run output into the root
    the migration just cleared.
    """
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path / "data"))

    assert AppPaths.default_working_dir() == tmp_path / "data" / "workspace"


def test_the_default_working_directory_can_be_created_on_demand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loading a configuration with no working directory set creates it."""
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path / "data"))

    created = AppPaths.default_working_dir(ensure_exists=True)

    assert created.is_dir()


def test_the_user_plugin_directory_sits_in_the_data_directory(tmp_path: Path) -> None:
    """Plugins the user installed are theirs, so they survive a release.

    They used to sit beside the executable, which is why replacing a release meant
    reinstalling them -- and why the shipped examples and the user's own plugins
    shared one directory with no way to tell them apart.
    """
    state = tmp_path / "state"
    paths = AppPaths(state_root=state, asset_root=tmp_path / "assets")

    assert paths.plugins == state / "plugins"


def test_a_development_plugins_folder_is_read_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The folder a developer keeps checkouts in, used in place of the real one."""
    monkeypatch.setattr("src.config.paths.IS_FROZEN", False)
    monkeypatch.setenv(DEV_PLUGINS_ENV_VAR, str(tmp_path / "checkouts"))

    assert dev_plugin_dirs() == (tmp_path / "checkouts",)


def test_several_development_folders_keep_the_order_they_were_written_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not sorted: the variable is written by hand, so first means first.

    Two folders holding one plugin id is a state the loader has to resolve, and
    the only answer that is not arbitrary is the one the developer typed first.
    """
    monkeypatch.setattr("src.config.paths.IS_FROZEN", False)
    first, second = tmp_path / "zeta", tmp_path / "alpha"
    monkeypatch.setenv(DEV_PLUGINS_ENV_VAR, pathsep.join((str(first), str(second))))

    assert dev_plugin_dirs() == (first, second)


def test_empty_segments_in_the_development_folders_are_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A trailing separator must not read as the current directory.

    `Path("")` is `Path(".")`, so keeping an empty segment would have the
    loader treat wherever the process was launched from as a plugin root.
    """
    monkeypatch.setattr("src.config.paths.IS_FROZEN", False)
    monkeypatch.setenv(
        DEV_PLUGINS_ENV_VAR, str(tmp_path / "checkout") + pathsep + pathsep + "  "
    )

    assert dev_plugin_dirs() == (tmp_path / "checkout",)


def test_no_development_folders_when_the_variable_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.config.paths.IS_FROZEN", False)
    monkeypatch.delenv(DEV_PLUGINS_ENV_VAR, raising=False)

    assert dev_plugin_dirs() == ()


def test_development_folders_are_refused_by_a_released_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plugin is trusted Python run inside the process.

    Moving where user data lives is bad; deciding what a release imports is
    worse, so the same gate covers both and this is the half that must not be
    allowed to rot.
    """
    monkeypatch.setattr("src.config.paths.IS_FROZEN", True)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "NfoForge.exe"))
    monkeypatch.setenv(DEV_PLUGINS_ENV_VAR, str(tmp_path / "checkout"))

    assert dev_plugin_dirs() == ()


def test_development_folders_are_honoured_by_the_debug_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same executable a migration rehearsal runs on.

    A plugin developer testing against the artefact that ships needs the
    override there too, and the debug executable is where that is allowed.
    """
    monkeypatch.setattr("src.config.paths.IS_FROZEN", True)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "NfoForge-debug.exe"))
    monkeypatch.setenv(DEV_PLUGINS_ENV_VAR, str(tmp_path / "checkout"))

    assert dev_plugin_dirs() == (tmp_path / "checkout",)
