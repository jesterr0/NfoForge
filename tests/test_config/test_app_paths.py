"""Coverage for the path object every other module asks for its locations.

Two roots go in and every path comes out of one of them. The old form bound
its paths as class attributes computed from `Path.cwd()` at import, which is
why a test that wanted a throwaway tree had to name five paths by hand and why
nothing could be reconfigured afterwards.
"""

from pathlib import Path
import sys

from platformdirs import user_data_dir
import pytest

from src.config.paths import (
    DATA_DIR_ENV_VAR,
    AppPaths,
    ConfigPaths,
    default_paths,
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

    assert paths.program == state / "config" / "program" / "conf.toml"
    assert paths.user_configs == state / "config" / "user"
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


def test_state_root_defaults_to_the_mutable_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = Path("/somewhere/runtime")
    monkeypatch.setattr("src.config.paths.RUNTIME_DIR", tree)
    monkeypatch.delenv(DATA_DIR_ENV_VAR, raising=False)

    assert default_paths().state_root == tree


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
    mutable = Path("/installed/runtime")
    monkeypatch.setattr("src.config.paths.IS_FROZEN", True)
    monkeypatch.setattr("src.config.paths.RUNTIME_DIR", mutable)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "NfoForge.exe"))
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path / "rehearsal"))

    assert default_paths().state_root == mutable


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
    tree = Path("/somewhere/runtime")
    monkeypatch.setattr("src.config.paths.RUNTIME_DIR", tree)
    monkeypatch.setattr("src.config.paths.IS_FROZEN", False)
    monkeypatch.setenv(DATA_DIR_ENV_VAR, "   ")

    assert default_paths().state_root == tree
